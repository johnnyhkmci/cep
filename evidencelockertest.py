#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
Google Cloud Platform (GCP) 自動化設定腳本 - Evidence Locker 獨立建置專用模組
適用於 Chrome Enterprise Premium (CEP) 可疑檔案隔離區設定。

完全加固版本（納入 4 項進階資安與穩健性建議）：
1. IAM 權限遵循最小特權原則（改推薦 Storage Object Admin）。
2. Bucket 建立時加入 --retention-period=30d 保護證據不被提前竄改或刪除 (WORM)。
3. 強制子程序語系為英文 (LC_ALL=C)，徹底解決多語系 CLI 錯誤判定問題。
4. 補齊 Data Access Audit Logs 存取稽核指引。
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# 參數設定區
LOCATION = "asia-east1"                      # KMS 與 Bucket 的地理位置
KEYRING_NAME = "cep-evidence-keyring"        # KMS 金鑰環名稱
KEY_NAME = "cep-evidence-key"                # KMS 加密金鑰名稱
BUCKET_PREFIX = "cep-evidence-locker"        # Bucket 名稱前綴

def init_logger():
    """初始化日誌設定"""
    logging.basicConfig(
        format="[%(asctime)s][%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

async def run_cmd(cmd_list, suppress_errors=False):
    """執行終端指令（強制使用英文語系，避免多語系 CLI 解析失敗；使用陣列傳遞避免 Command Injection）"""
    logging.debug(f"執行指令: {' '.join(cmd_list)}")
    
    # 強制將子程序環境變數設為英文，避免 zh-TW 等語系導致 stderr 關鍵字判斷失效
    cmd_env = os.environ.copy()
    cmd_env["CLOUDSDK_OUTPUT_LANGUAGE"] = "en"
    cmd_env["LC_ALL"] = "C"

    process = await asyncio.create_subprocess_exec(
        *cmd_list,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=cmd_env
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        err_msg = stderr.decode()
        # 僅當明確為「資源已存在」時忽略錯誤
        if suppress_errors and ("already exists" in err_msg.lower() or "alreadyexists" in err_msg.lower()):
            return stdout, stderr, 0
        logging.critical(f"❌ 指令執行失敗: {' '.join(cmd_list)}\n錯誤細節:\n{err_msg}")
        sys.exit(process.returncode)
        
    return stdout, stderr, process.returncode

async def get_project_info():
    """取得當前專案 ID 與 專案編號"""
    stdout, _, _ = await run_cmd(["gcloud", "config", "get-value", "project"])
    project_id = stdout.decode().strip()
    
    stdout, _, _ = await run_cmd(["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"])
    project_number = stdout.decode().strip()
    
    return project_id, project_number

async def setup_evidence_locker():
    """執行 Evidence Locker 核心配置流程"""
    print("\n" + "=" * 60)
    print("🛡️  開始部署 CEP Evidence Locker (已納入最小權限與 WORM 保護)")
    print("=" * 60)

    # 1. 確認專案資訊
    project_id, project_number = await get_project_info()
    bucket_name = f"{BUCKET_PREFIX}-{project_number}"
    print(f"▶ 目標專案 ID : {project_id}")
    print(f"▶ 目標 Bucket : gs://{bucket_name}")
    print(f"▶ 部署區域    : {LOCATION}\n")

    # 2. 啟用必要 API
    logging.info("⏳ 1/5 正在啟用 Cloud Storage、Cloud KMS 與 Cloud Resource Manager APIs...")
    await run_cmd([
        "gcloud", "services", "enable",
        "storage.googleapis.com",
        "cloudkms.googleapis.com",
        "cloudresourcemanager.googleapis.com"
    ])
    
    # 3. 建立 KMS 金鑰 (計算 90 天後的 UTC 時間點以滿足 CLI 規範)
    logging.info("⏳ 2/5 正在建立客戶管理式加密金鑰 (CMEK)...")
    await run_cmd([
        "gcloud", "kms", "keyrings", "create", KEYRING_NAME,
        f"--location={LOCATION}", f"--project={project_id}"
    ], suppress_errors=True)
    
    next_rotation_time = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

    await run_cmd([
        "gcloud", "kms", "keys", "create", KEY_NAME,
        f"--keyring={KEYRING_NAME}", f"--location={LOCATION}",
        "--purpose=encryption/decryption", f"--project={project_id}",
        "--rotation-period=90d",
        f"--next-rotation-time={next_rotation_time}"
    ], suppress_errors=True)

    # 4. 授權 GCS 系統服務帳戶
    logging.info("⏳ 3/5 正在授權 GCS 系統帳戶 KMS 加解密權限...")
    stdout, _, _ = await run_cmd(["gcloud", "storage", "service-agent", f"--project={project_id}"])
    gcs_sa = stdout.decode().strip()
    
    await run_cmd([
        "gcloud", "kms", "keys", "add-iam-policy-binding", KEY_NAME,
        f"--keyring={KEYRING_NAME}", f"--location={LOCATION}",
        f"--member=serviceAccount:{gcs_sa}",
        "--role=roles/cloudkms.cryptoKeyEncrypterDecrypter",
        f"--project={project_id}"
    ])

    # 5. 建立綁定 CMEK 的 GCS Bucket 並直接套用資安與 30 天 Retention (WORM) 防護
    logging.info("⏳ 4/5 正在建立儲存槽並套用資安控管與 30 天資料防竄改保留政策 (Retention Policy)...")
    kms_path = f"projects/{project_id}/locations/{LOCATION}/keyRings/{KEYRING_NAME}/cryptoKeys/{KEY_NAME}"
    await run_cmd([
        "gcloud", "storage", "buckets", "create", f"gs://{bucket_name}",
        f"--project={project_id}", f"--location={LOCATION}",
        f"--default-kms-key={kms_path}",
        "--public-access-prevention",
        "--uniform-bucket-level-access",
        "--retention-period=30d"  # 新增：WORM 機制，防止 30 天內被竄改或提早刪除
    ], suppress_errors=True)

    # 6. 設定 TTL 檔案生命週期 (30 天自動刪除)
    logging.info("⏳ 5/5 正在套用檔案生命週期規則 (超過 30 天自動刪除)...")
    lifecycle_json = {
        "rule": [
            {
                "action": {"type": "Delete"},
                "condition": {"age": 30}
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tf:
        json.dump(lifecycle_json, tf)
        temp_path = tf.name

    try:
        await run_cmd(["gcloud", "storage", "buckets", "update", f"gs://{bucket_name}", f"--lifecycle-file={temp_path}"])
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # 結語：指引後續 Google Workspace Admin 核心操作與最小權限設定
    print("\n" + "=" * 60)
    print("✅ Evidence Locker GCP 基礎設施部署完成！")
    print(f"👉 您的 Bucket 名稱： gs://{bucket_name}")
    print("-" * 60)
    print("【⚠️ 後續必要操作 Checklist】請依規範完成以下設定：")
    print("1. 前往 Google Workspace Admin 控制台 > 安全性 > 規則 (DLP)。")
    print("2. 於可疑檔案調查設定中，填入此 Bucket 名稱。")
    print("3. 點擊「產生服務帳戶 (Generate a service account)」並複製其 Email。")
    print(f"4. 返回 GCP 專案 ({project_id}) IAM 頁面，新增該服務帳戶並授予：")
    print("   👉 儲存空間物件管理員 (roles/storage.objectAdmin)")
    print("   （恪守最小權限原則，嚴禁給予 Storage Admin 以避免 Bucket 被整座刪除）")
    print("5. 建議前往 IAM & Admin > Audit Logs，搜尋 Google Cloud Storage，")
    print("   將「Data Read」與「Data Write」稽核日誌開啟，以完整記錄證據存取軌跡。")
    print("=" * 60 + "\n")

async def main():
    init_logger()
    try:
        await setup_evidence_locker()
    except KeyboardInterrupt:
        print("\n⚠️ 使用者已手動中斷執行。")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
