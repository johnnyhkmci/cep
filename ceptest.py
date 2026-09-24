#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Copyright 2020 Google LLC (Modified for CEP & Google Apps Script Deployment)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
Google Cloud Platform (GCP) 自動化設定腳本 - Chrome Enterprise Premium (CEP) 部署專用
主要功能：
1. 建立專案並設為預設 (create_project)
2. 檢查並驗證 GCP API 服務條款接受狀態 (verify_tos_accepted)
3. 平行啟用 CEP 與 Google Apps Script 相關 API (enable_apis)
4. 建立 CEP 專用服務帳戶 (create_service_account)
5. 產生全網域委派 (Domain-Wide Delegation, DWD) 授權連結 (authorize_service_account)
6. 引導設定 OAuth 同意畫面 (OAuth Consent Screen)
7. 取得「GCP 專案編號 (Project Number)」並引導綁定至 Google Sheet 內建的 Apps Script
"""


import asyncio
import datetime
import json
import logging
import os
import sys
import time
import urllib.parse


VERSION = "2.0-CEP-GAS"


# 工具識別設定 (GCP 專案 ID 只能包含小寫英文字母、數字與連字號，且必須以字母開頭)
TOOL_NAME = "cep-poc"
TOOL_NAME_FRIENDLY = "Chrome Enterprise Premium (CEP) PoC"
# GCP 專案顯示名稱 (Display Name) 限制：長度 4~30 字元，不可包含括號 () 等特殊字元
PROJECT_NAME_PREFIX = "CEP PoC"
TOOL_HELP_CENTER_URL = "https://github.com/johnnyhkmci/CEP"


# CEP 與 Apps Script 部署所需的 API 清單
# 注意：若包含 admin.googleapis.com，必須排在第一位，以利服務條款 (ToS) 檢查流程
APIS = [
   "admin.googleapis.com",
   "cloudidentity.googleapis.com",
   "accesscontextmanager.googleapis.com",
   "cloudresourcemanager.googleapis.com",
   "chromepolicy.googleapis.com",
   "beyondcorp.googleapis.com",      # Chrome Enterprise Premium (BeyondCorp) 核心 API
   "script.googleapis.com",          # Google Apps Script 專案連結必要 API
   "sheets.googleapis.com",          # Google Sheets API (若需要後端 API 呼叫)
   "chromeuxreport.googleapis.com"   # Chrome 相關報表 API (選用)
]

# Chrome Enterprise Premium (CEP) 操作帳戶所需在「組織層級 (Organization)」具備的角色
CEP_ORG_ROLES = [
   "roles/beyondcorp.admin",         # Cloud BeyondCorp 管理員
   "roles/iam.supportUser",           # 支援使用者
   "roles/accesscontextmanager.policyAdmin"    # Access Context Manager 管理員
]


# 服務帳戶向 Google Workspace 申請全網域委派 (DWD) 所需的 OAuth 範圍 (Scopes)
SCOPES = [
   "https://www.googleapis.com/auth/cloud-identity.policies",
   "https://www.googleapis.com/auth/admin.directory.orgunit.readonly",
   "https://www.googleapis.com/auth/spreadsheets",
   "https://www.googleapis.com/auth/cloud-platform",
   "https://www.googleapis.com/auth/script.external_request",
   "https://www.googleapis.com/auth/chrome.management.policy",
   "https://www.googleapis.com/auth/admin.directory.orgunit"
]


# Google Workspace 管理後台全網域委派深層連結範本 (Deep Link)
DWD_URL_FORMAT = (
   "https://admin.google.com/ac/owl/domainwidedelegation?"
   "overwriteClientId=true&clientIdToAdd={}&clientScopeToAdd={}"
)


# GCP OAuth 同意畫面與專案設定網址範本
OAUTH_CONSENT_URL_FORMAT = (
   "https://console.cloud.google.com/apis/credentials/consent?project={}"
)
PROJECT_SETTINGS_URL_FORMAT = (
   "https://console.cloud.google.com/iam-admin/settings?project={}"
)
# Chrome Enterprise Premium (CEP) / Context-Aware Access (CAA) 組織控制台標準網址
CEP_CONSOLE_URL_FORMAT = (
   "https://console.cloud.google.com/security/caa?organizationId={}"
)


def init_logger():
   """初始化日誌設定：詳細 DEBUG 寫入日誌檔，INFO 與重要提示輸出至終端螢幕"""
   logging.basicConfig(
       filename=f"{TOOL_NAME}_setup.log",
       format="[%(asctime)s][%(levelname)s] %(message)s",
       datefmt="%Y-%m-%dT%H:%M:%SZ",
       level=logging.DEBUG
   )
   console = logging.StreamHandler()
   console.setLevel(logging.INFO)
   formatter = logging.Formatter("%(message)s")
   console.setFormatter(formatter)
   logging.getLogger("").addHandler(console)




async def retryable_command(
   command,
   max_num_retries=3,
   retry_delay=5,
   suppress_errors=False,
   require_output=False,
   stdin=None
):
   """執行終端指令的非同步共用函式，支援自動重試與錯誤處理機制"""
   num_tries = 1
   while num_tries <= max_num_retries:
       logging.debug("正在執行指令 (第 %d 次嘗試): %s", num_tries, command)
       process = await asyncio.create_subprocess_shell(
           command,
           stdin=asyncio.subprocess.PIPE if stdin else None,
           stdout=asyncio.subprocess.PIPE,
           stderr=asyncio.subprocess.PIPE
       )
       stdout, stderr = await process.communicate(input=stdin.encode() if stdin else None)
       return_code = process.returncode


       logging.debug("stdout: %s", stdout.decode())
       logging.debug("stderr: %s", stderr.decode())
       logging.debug("回傳代碼: %d", return_code)


       if return_code == 0:
           if not require_output or (require_output and stdout):
               return (stdout, stderr, return_code)


       if num_tries < max_num_retries:
           num_tries += 1
           await asyncio.sleep(retry_delay)
       elif suppress_errors:
           return (stdout, stderr, return_code)
       else:
           logging.critical("執行指令失敗: %s\n\nstderr:\n`%s`", command, stderr.decode())
           sys.exit(return_code)




async def get_project_id():
   """取得當前 gcloud CLI 作用中的專案 ID (例如 cep-1694820000000)"""
   command = "gcloud config get-value project"
   project_id, _, _ = await retryable_command(command, require_output=True)
   return project_id.decode().rstrip()




async def get_project_number():
   """
   取得當前 GCP 專案的純數字編號 (Project Number, 例如 102938475612)。
   這是 Google Apps Script「關聯標準 GCP 專案 (Change Project)」時必須填入的唯一識別碼。
   """
   project_id = await get_project_id()
   command = f'gcloud projects describe {project_id} --format="value(projectNumber)"'
   project_number, _, _ = await retryable_command(command, require_output=True)
   return project_number.decode().rstrip()




async def get_service_account_id():
   """取得目前專案中服務帳戶的唯一數字 ID (Unique ID / OAuth2 Client ID)"""
   command = 'gcloud iam service-accounts list --format="value(uniqueId)"'
   service_account_id, _, _ = await retryable_command(command, require_output=True)
   return service_account_id.decode().rstrip()




async def get_service_account_email():
   """取得目前專案中服務帳戶的 Email 地址"""
   command = 'gcloud iam service-accounts list --format="value(email)"'
   service_account_email, _, _ = await retryable_command(command, require_output=True)
   return service_account_email.decode().rstrip()




async def get_admin_user_email():
   """取得當前執行 gcloud 的管理員帳號 Email"""
   command = 'gcloud auth list --filter=status:ACTIVE --format="value(account)"'
   admin_user_email, _, _ = await retryable_command(command, require_output=True)
   return admin_user_email.decode().rstrip()




async def get_organization_id():
   """取得當前使用者所屬的 GCP/Workspace 組織 ID (純數字)"""
   command = 'gcloud organizations list --format="value(ID)"'
   org_id, _, return_code = await retryable_command(command, suppress_errors=True)
   if return_code == 0 and org_id:
       return org_id.decode().strip().split("\n")[0]
   return None




async def grant_cep_organization_roles():
   """
   在「組織層級 (Organization)」為當前管理員帳戶賦予 CEP 所需的 IAM 角色：
   - roles/beyondcorp.admin (Cloud BeyondCorp 管理員)
   - roles/iam.supportUser (支援使用者)
   若權限不足或未找到組織，將引導使用者前往 GCP 網頁後台手動完成授權。
   """
   logging.info("正在檢查並設定 Chrome Enterprise Premium 組織層級 IAM 權限...")
   admin_email = await get_admin_user_email()
   org_id = await get_organization_id()

   if not org_id:
       logging.warning("⚠️ 找不到組織 ID，可能當前帳號未綁定組織或無組織檢視權限。")
       print("\n" + "=" * 80)
       print("⚠️  注意：未偵測到組織 ID (Organization ID)")
       print("請確認您的 Google Cloud 專案是否建立在組織 (如 masterconcept.ai) 之下。")
       print(f"請至 GCP Console 確認當前帳戶 ({admin_email}) 已取得下列組織角色：")
       for role in CEP_ORG_ROLES:
           print(f"  👉 {role}")
       print("=" * 80 + "\n")
       input("👉 確認完成後請按 Enter 鍵繼續...")
       return

   print(f"\n偵測到組織 ID: {org_id}，正在為帳戶 {admin_email} 綁定 CEP 組織角色...")

   for role in CEP_ORG_ROLES:
       cmd = (
           f"gcloud organizations add-iam-policy-binding {org_id} "
           f"--member=\"user:{admin_email}\" "
           f"--role=\"{role}\""
       )
       _, stderr, return_code = await retryable_command(
           cmd, max_num_retries=1, suppress_errors=True
       )
       if return_code == 0:
           logging.info("成功指派組織角色: %s ✅", role)
       else:
           err_str = stderr.decode()
           logging.warning("自動指派角色 %s 失敗：%s", role, err_str)
           print(f"\n⚠️  自動授予角色 {role} 失敗 (可能需要組織管理員 Organization Admin 權限)。")
           print(f"請前往此連結，手動為 {admin_email} 新增「{role}」角色：")
           print(f"👉 https://console.cloud.google.com/iam-admin/iam?organizationId={org_id}\n")
           answer = input("❓ 若您已在後台完成授權，請按 Enter 鍵繼續，或輸入 'n' 離開：")
           if answer.strip().lower() == "n":
               sys.exit(0)

   logging.info("Chrome Enterprise Premium 組織權限設定完成 ✅")




async def guide_cep_trial_activation():
   """
   引導管理員在 GCP Console 開通 Chrome Enterprise Premium (CEP) 60 天免費試用。
   使用官方標準 /security/caa 組織頁面路徑。
   """
   org_id = await get_organization_id()
   if org_id:
       cep_url = CEP_CONSOLE_URL_FORMAT.format(org_id)
   else:
       cep_url = "https://console.cloud.google.com/security/caa"

   print("\n" + "=" * 80)
   print("⚠️  步驟：開通 Chrome Enterprise Premium (CEP) 免費試用")
   print("CEP 60 天免費試用涉及組織合約與條款確認，需至控制台手動點擊開通。")
   print(f"請在瀏覽器中開啟下列標準控制台網址：\n\n👉 {cep_url}\n")
   print("操作說明：")
   print(" 1. 確認頁面頂部選取的資源為您的【組織】(例如 masterconcept.ai)")
   print(" 2. 點擊頂部橫幅中的藍色按鈕【申請免費試用】")
   print(" 3. 依提示完成確認即開通 60 天 (最多 5,000 人) 試用額度")
   print("=" * 80 + "\n")
   input("👉 點擊開通完成後，請按 Enter 鍵繼續下一步...")




async def create_project():
   """動態產生專案名稱與專案 ID，在 GCP 建立專案並設為當前預設"""
   logging.info("正在建立 GCP 專案...")
   # Project ID 規則：6-30 字元，小寫字母、數字、連字號，必須以字母開頭
   project_id = f"{TOOL_NAME}-{int(time.time() * 1000)}"
   # Project Display Name 規則：4-30 字元，不可包含括號 ()
   # "CEP PoC " (8) + "20260916-1430" (13) = 21 字元，完全符合 <= 30 的限制
   timestamp_short = datetime.datetime.now().strftime("%Y%m%d-%H%M")
   project_name = f"{PROJECT_NAME_PREFIX} {timestamp_short}"
  
   await retryable_command(
       f"gcloud projects create {project_id} --name \"{project_name}\" --set-as-default"
   )
   logging.info("專案 %s (名稱: %s) 已成功建立 ✅", project_id, project_name)




async def verify_tos_accepted():
   """
   驗證使用者是否已同意 Google API 服務條款 (Terms of Service)
   嘗試啟用清單中的第一個 API (admin.googleapis.com)，若尚未同意條款則引導點擊同意。
   """
   logging.info("正在驗證 API 服務條款 (Terms of Service) 接受狀態...")
   tos_accepted = False
  
   while APIS and not tos_accepted:
       command = f"gcloud services enable {APIS[0]}"
       _, stderr, return_code = await retryable_command(
           command, max_num_retries=1, suppress_errors=True
       )
       if return_code:
           err_str = stderr.decode()
           if "UREQ_TOS_NOT_ACCEPTED" in err_str:
               if "universal" in err_str:
                   logging.debug("尚未接受 Google APIs 通用服務條款")
                   print("\n您必須先同意 Google APIs 通用服務條款。")
                   print("請前往此連結點選「同意 (Accept)」：")
                   print("👉 https://console.developers.google.com/terms/universal\n")
               elif "appsadmin" in err_str:
                   logging.debug("尚未接受 Google Apps Admin APIs 服務條款")
                   print("\n您必須先同意 Google Apps Admin APIs 服務條款。")
                   print("請前往此連結點選「同意 (Accept)」：")
                   print("👉 https://console.developers.google.com/terms/appsadmin\n")
              
               answer = input("❓ 若您已同意服務條款，請按 Enter 鍵重試，或輸入 'n' 離開：")
               if answer.strip().lower() == "n":
                   sys.exit(0)
           else:
               logging.critical("啟用 API 發生未預期錯誤：%s", err_str)
               sys.exit(1)
       else:
           tos_accepted = True
          
   logging.info("API 服務條款驗證完成 ✅")




async def enable_api(api):
   """啟用單一 GCP 服務 API"""
   command = f"gcloud services enable {api}"
   await retryable_command(command)




async def enable_apis():
   """平行非同步啟用剩餘的所有必要 API"""
   logging.info("正在非同步啟用所有必要的 API 服務 (包含 Apps Script API)...")
   # 第一個 API 在 verify_tos_accepted 階段已啟用
   enable_api_calls = [enable_api(api) for api in APIS[1:]]
   await asyncio.gather(*enable_api_calls)
   logging.info("所有必要 API 服務已成功啟用 ✅")




async def create_service_account():
   """在 GCP 專案中建立指定的服務帳戶 (Service Account)"""
   logging.info("正在建立 CEP 服務帳戶 (Service Account)...")
   service_account_name = f"{TOOL_NAME}-service-account"
   service_account_display_name = f"{TOOL_NAME_FRIENDLY} Service Account"
   await retryable_command(
       f"gcloud iam service-accounts create {service_account_name} "
       f'--display-name "{service_account_display_name}"'
   )
   logging.info("服務帳戶 %s 建立完成 ✅", service_account_name)




async def authorize_service_account():
   """
   產生 Google Workspace 全網域委派 (Domain-Wide Delegation, DWD) 的授權 URL。
   引導管理員點擊授權連結，將 Scopes 綁定至該服務帳戶的 Client ID。
   """
   service_account_id = await get_service_account_id()
   scopes_str = urllib.parse.quote(",".join(SCOPES), safe="")
   authorize_url = DWD_URL_FORMAT.format(service_account_id, scopes_str)
  
   print("\n" + "=" * 80)
   print("⚠️  步驟一：完成 Google Workspace 全網域委派授權 (DWD)")
   print(f"服務帳戶 ID (Client ID): {service_account_id}")
   print(f"請在瀏覽器中開啟下列深層連結完成授權：\n\n👉 {authorize_url}\n")
   print("在 Google Workspace 管理後台中確認已加入 Scopes 並點選「授權 (Authorize)」。")
   print("=" * 80 + "\n")
   input("👉 完成授權後請按 Enter 繼續下一階段...")




async def guide_oauth_consent_screen():
   """
   引導設定 OAuth 同意畫面。
   Google Apps Script 在綁定標準 GCP 專案時，要求該專案必須先配置 OAuth 同意畫面。
   針對組織內部使用，強烈建議設定為「內部 (Internal)」，免除 Google 繁瑣的應用程式驗證。
   """
   project_id = await get_project_id()
   consent_url = OAUTH_CONSENT_URL_FORMAT.format(project_id)


   print("\n" + "=" * 80)
   print("⚠️  步驟二：設定 GCP OAuth 同意畫面 (OAuth Consent Screen)")
   print("Google Apps Script 連結標準專案前，GCP 專案必須完成 OAuth 同意畫面初始化。")
   print(f"請前往此網址配置：\n👉 {consent_url}\n")
   print("建議配置步驟：")
   print(" 1. 使用者類型 (User Type) 選擇：【內部 (Internal)】，點選「建立」")
   print(f" 2. 應用程式名稱填入：{TOOL_NAME_FRIENDLY}")
   print(" 3. 填入您的「使用者支援電子郵件」與「開發人員聯絡資訊」")
   print(" 4. 點選「儲存並繼續」，其餘範圍 (Scopes) 可直接跳過，最後儲存即可。")
   print("=" * 80 + "\n")
   input("👉 完成 OAuth 同意畫面設定後，請按 Enter 鍵獲取專案編號...")




async def show_apps_script_link_guidance():
   """
   取得 GCP 專案編號 (Project Number)，並提供清楚的 Google Sheet Apps Script 關聯步驟引導。
   """
   project_id = await get_project_id()
   project_number = await get_project_number()
   sa_email = await get_service_account_email()


   print("\n" + "#" * 80)
   print("🎉 GCP 專案與 API 已全數準備完畢！")
   print("#" * 80)
   print(f"\n【專案重要資訊】")
   print(f" ▶ 專案 ID (Project ID)         : {project_id}")
   print(f" ▶ 專案編號 (GCP Project Number) : {project_number}  <-- 【請複製此數字】")
   print(f" ▶ 服務帳戶 (Service Account)   : {sa_email}")
   print("\n" + "-" * 80)
   print("📋 【步驟三：將專案綁定到您的 Google Sheet / Apps Script】")
   print("-" * 80)
   print("1. 開啟您用於部署 CEP 的 Google Sheet 文件。")
   print("2. 點選頂端選單的 【擴充功能 (Extensions)】 -> 【Apps Script】。")
   print("3. 在 Apps Script 編輯器左側導覽列中，點選齒輪圖示 【專案設定 (Project Settings)】。")
   print("4. 向下滾動到 【Google Cloud Platform (GCP) 專案】 區塊。")
   print("5. 點選 【變更專案 (Change project)】 按鈕。")
   print(f"6. 在「GCP 專案編號」欄位中貼上： {project_number}")
   print("7. 點選 【設定專案 (Set project)】 完成綁定！")
   print("-" * 80)
   print("💡 綁定完成後，您的 Apps Script 即已獲得本專案啟用的所有 API 權限，")
   print("   後續執行腳本部署環境時，請直接在 Google Sheet / Apps Script 介面進行授權即可。")
   print("#" * 80 + "\n")




async def main():
   """腳本主流程控制進入點"""
   init_logger()
   os.system("clear" if os.name != "nt" else "cls")
  
   welcome_text = (
       f"======================================================================\n"
       f"  歡迎使用 {TOOL_NAME_FRIENDLY} Google Sheet & Apps Script 自動化初始化工具\n"
       f"======================================================================\n"
       f"本腳本將為您建立專屬 GCP 專案，準備相關 API，並產出專案編號供 Google Sheet 綁定：\n\n"
       f" 1. 建立獨立 GCP 專案並設為預設\n"
       f" 2. 自動啟用 CEP、Apps Script 與 Sheets API\n"
       f" 3. 建立專屬服務帳戶 (Service Account)\n"
       f" 4. 引導完成 Google Workspace 全網域委派 (DWD)\n"
       f" 5. 引導配置內部專案 OAuth 同意畫面\n"
       f" 6. 產出 GCP Project Number 並引導綁定至 Google Sheet 擴充功能\n\n"
       f"（本流程免下載任何 JSON 金鑰，兼具企業資訊安全與架構簡潔性）\n"
       f"手動文件參考：{TOOL_HELP_CENTER_URL}\n"
       f"======================================================================\n"
   )
   print(welcome_text)
   response = input("❓ 按 Enter 鍵開始自動執行，或輸入 'n' 離開：")
   if response.strip().lower() == "n":
       sys.exit(0)


   # 依序執行自動化步驟
   await create_project()
   await verify_tos_accepted()
   await enable_apis()
   await grant_cep_organization_roles()
   await guide_cep_trial_activation()
   await create_service_account()
   await authorize_service_account()
   await guide_oauth_consent_screen()
   await show_apps_script_link_guidance()


   logging.info("🎉 CEP 雲端環境設定流程結束！✅")




if __name__ == "__main__":
   asyncio.run(main())
