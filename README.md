# Chrome Enterprise Premium
## Google Workspace 建立用於驗證的服務帳戶
### 使用自動化指令碼建立帳戶
1. 開啟 Google Cloud，將帳戶增加「機構政策管理員」(Organization Policy Administrator)權限（[連結](https://console.cloud.google.com/iam-admin/iam)）。
或是下指令```gcloud organizations add-iam-policy-binding [Organization Id] --member=user:[Supper Admin Email] --role=roles/orgpolicy.policyAdmin```
2. 將【「停用服務帳戶金鑰建立功能」的政策】(Policy for Disable service account key creation)（[連結](https://console.cloud.google.com/iam-admin/orgpolicies/iam-disableServiceAccountKeyCreation)）的設定修改規則為「停用」(off)，顯示「未強制執行」(Not enforced)。
或是下指令```gcloud resource-manager org-policies disable-enforce iam.disableServiceAccountKeyCreation --organization=[Organization Id]```
3. 在瀏覽器視窗中開啟 [Cloud Shell 編輯器](https://ssh.cloud.google.com/cloudshell/editor?shellonly=true)
4. 輸入 
```python3 <(curl -s -S -L https://cutt.ly/cloudmCSA)```
5. 完成 Cloud Shell 視窗中的步驟
6. 點選「下載」，將內含服務帳戶用戶端 ID 的 JSON 檔案下載到電腦上
7. 完成「[建立 OAuth 網路用戶端 ID](https://support.google.com/workspacemigrate/answer/9222992)」中的步驟
