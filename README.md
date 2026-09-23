# Chrome Enterprise Premium (CEP) & Google Apps Script 自動化部署工具

本專案提供一個基於 Python (Asyncio) 的 GCP 自動化初始化腳本，專為簡化 **Chrome Enterprise Premium (CEP)** 與 **Google Apps Script (GAS)** 的整合部署而設計。透過自動化指令與互動式引導，能快速建立 GCP 專案、啟用必要 API、配置組織層級 IAM 權限、建立服務帳戶並引導完成全網域委派與 Apps Script 專案綁定。

---

## 🌟 主要功能

1. **自動建立與設定 GCP 專案**：動態產生符合命名規範的專案 ID 與顯示名稱，並自動設為當前預設專案。
2. **API 服務條款驗證與非同步啟用**：自動檢測 API 服務條款 (ToS) 接受狀態，並以非同步平行方式啟用 CEP 與 Apps Script 所需的所有 GCP API。
3. **組織層級 IAM 角色自動指派**：檢查並為管理員帳號指派 BeyondCorp、Access Context Manager 及支援使用者等組織層級 (Organization) IAM 角色。
4. **CEP 試用引導**：提供深層連結引導管理員前往 Console 開通 Chrome Enterprise Premium 60 天免費試用。
5. **服務帳戶與全網域委派 (DWD)**：自動建立 CEP 專用服務帳戶 (Service Account)，並生成 Google Workspace 全網域委派 (Domain-Wide Delegation) 的直達授權連結。
6. **OAuth 同意畫面與 Apps Script 綁定引導**：引導配置內部 (Internal) OAuth 同意畫面，並產出 GCP 專案編號 (Project Number)，方便直接綁定至 Google Sheet 內建的 Apps Script 專案。

---

## 📋 執行環境與前置需求

* **推薦環境**：**GCP Cloud Shell**（已內建 `gcloud` CLI 及 Python 3 環境，免去本地環境配置與認證步驟）。
* **權限要求**：
  * 執行帳號需具備 GCP 專案建立權限。
  * 需具備 Google Cloud 組織層級角色指派權限（或組織管理員 Organization Admin 權限）。
  * 需具備 Google Workspace 超級管理員權限（用於執行全網域委派授權）。

---

## 🔌 預設啟用的 API 清單

| API 服務名稱 | 說明 |
| :--- | :--- |
| `admin.googleapis.com` | Google Workspace Admin SDK |
| `cloudidentity.googleapis.com` | Cloud Identity API |
| `accesscontextmanager.googleapis.com` | Access Context Manager API |
| `cloudresourcemanager.googleapis.com` | Cloud Resource Manager API |
| `chromepolicy.googleapis.com` | Chrome Policy API |
| `beyondcorp.googleapis.com` | BeyondCorp / Chrome Enterprise Premium 核心 API |
| `script.googleapis.com` | Google Apps Script API |
| `sheets.googleapis.com` | Google Sheets API |
| `chromeuxreport.googleapis.com` | Chrome UX Report API (選用) |

---

## 🚀 快速開始

請在 **GCP Cloud Shell** 終端機中，直接貼上並執行以下單行指令即可啟動自動化部署流程：

```bash
python3 <(curl -s -S -L https://raw.githubusercontent.com/johnnyhkmci/cep/main/cep.py)
```

---

## 📋 執行流程說明

腳本啟動後，將依序執行以下步驟（部分步驟需於瀏覽器配合點擊確認）：

1. **建立專案**：自動建立格式為 `cep-poc-<timestamp>` 的專案並設為預設。
2. **驗證與啟用 API**：自動啟用所有清單中的 Google API。若提示需同意條款，請依終端機顯示之連結前往同意。
3. **組織角色設定**：自動為您的管理員帳號賦予 `roles/beyondcorp.admin` 等組織角色。
4. **開通 CEP 試用**：點擊終端機產出的專屬 Console 連結，於頂部點選「申請免費試用」。
5. **授權全網域委派 (DWD)**：點擊終端機產出的深層連結，前往 Google Workspace 管理後台確認並點選「授權」。
6. **設定 OAuth 同意畫面**：依引導前往 GCP Console 將 OAuth 同意畫面設定為【內部 (Internal)】。
7. **綁定 Apps Script**：複製腳本最後輸出的 **GCP 專案編號 (Project Number)**，至 Google Sheet 的 Apps Script 設定中點選「變更專案」並貼上完成綁定。

---

## 📄 日誌與排錯

* 腳本執行時會自動於當前工作目錄下建立 `cep-poc_setup.log` 日誌檔案。
* 若執行過程遭遇錯誤，可檢視該檔案中的詳細 `DEBUG` 層級資訊進行故障排除。
