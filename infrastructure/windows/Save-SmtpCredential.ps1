param(
    [string]$SenderEmail = 'kredavto@mail.ru',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

function Save-MailerCredential {
    param([string]$Directory, [System.Management.Automation.PSCredential]$Credential)
    if (Test-Path -LiteralPath $Directory) {
        if ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Credential directory must not be a link.'
        }
    } else {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetOwner($identity)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'
    )
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Directory -AclObject $acl
    $destination = Join-Path $Directory 'smtp.credential.xml'
    # Export-Clixml encrypts SecureString with Windows DPAPI for this Windows user.
    # No overwrite: rotating a credential requires an explicit separate operation.
    $Credential | Export-Clixml -LiteralPath $destination -NoClobber
    return $destination
}

if ($ValidateOnly) { return }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$credentialDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'PremiumB2BMailer\credentials'
$form = New-Object Windows.Forms.Form
$form.Text = 'Premium B2B Mailer - SMTP Mail.ru'
$form.ClientSize = New-Object Drawing.Size(620, 350)
$form.StartPosition = 'CenterScreen'
$form.WindowState = 'Normal'
$form.ShowInTaskbar = $true
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.Font = New-Object Drawing.Font('Segoe UI', 10)

$instructions = New-Object Windows.Forms.Label
$instructions.Location = New-Object Drawing.Point(20, 18)
$instructions.Size = New-Object Drawing.Size(580, 130)
$instructions.Text = "Отправитель: $SenderEmail`r`nSMTP: smtp.mail.ru:465 (SSL/TLS)`r`n`r`nВведите пароль приложения Mail.ru с правом «Только отправка писем». Не обычный пароль от почты. Он будет зашифрован Windows и сохранён только на этом компьютере."
$form.Controls.Add($instructions)
$password = New-Object Windows.Forms.TextBox
$password.Location = New-Object Drawing.Point(20, 150)
$password.Size = New-Object Drawing.Size(580, 30)
$password.UseSystemPasswordChar = $true
$form.Controls.Add($password)
$notice = New-Object Windows.Forms.Label
$notice.Location = New-Object Drawing.Point(20, 190)
$notice.Size = New-Object Drawing.Size(580, 90)
$notice.Text = "Хранилище: $credentialDirectory`r`n`r`nЭто окно не отправляет письма и не меняет сервер. После сохранения вернитесь в Codex и напишите «Сохранил» для завершения подключения."
$form.Controls.Add($notice)
$save = New-Object Windows.Forms.Button
$save.Text = 'Сохранить зашифрованно'
$save.Location = New-Object Drawing.Point(20, 295)
$save.Size = New-Object Drawing.Size(280, 36)
$form.Controls.Add($save)
$cancel = New-Object Windows.Forms.Button
$cancel.Text = 'Отмена'
$cancel.Location = New-Object Drawing.Point(440, 295)
$cancel.Size = New-Object Drawing.Size(160, 36)
$cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancel)
$form.CancelButton = $cancel
$form.AcceptButton = $save
$save.Add_Click({
    if ([string]::IsNullOrWhiteSpace($password.Text)) { return }
    $secure = $null
    try {
        $secure = ConvertTo-SecureString $password.Text -AsPlainText -Force
        $credential = New-Object Management.Automation.PSCredential($SenderEmail, $secure)
        $null = Save-MailerCredential -Directory $credentialDirectory -Credential $credential
        $password.Clear()
        [Windows.Forms.MessageBox]::Show(
            'Сохранено в зашифрованном виде. Вернитесь в Codex и напишите «Сохранил».',
            'Premium B2B Mailer'
        ) | Out-Null
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        [Windows.Forms.MessageBox]::Show(
            'Не удалось сохранить. Возможно, файл уже существует. Не отправляйте пароль в чат; сообщите Codex об ошибке.',
            'Premium B2B Mailer'
        ) | Out-Null
    } finally {
        if ($null -ne $secure) { $secure.Dispose() }
        $credential = $null
    }
})
$form.Add_Shown({ $password.Focus(); $form.Activate() })
try { $null = $form.ShowDialog() } finally { $password.Clear(); $form.Dispose() }
