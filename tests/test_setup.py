import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

class SetupTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
    def test_update_preserves_tailscale_and_custom_properties(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            config=root/'KosekControlCenter/config.json'
            config.parent.mkdir()
            route={'enabled':True,'profileId':'synthetic','account':'test@example.invalid'}
            config.write_text(json.dumps({'instances':[{'name':'TEST','tailscale':route,'custom':'keep'}]}))
            driver=root/'test.ps1'
            script=Path(__file__).resolve().parents[1]/'scripts/setup-instance.ps1'
            driver.write_text("param([string]$Script)\nfunction Read-Host { param($Prompt,[switch]$AsSecureString); ConvertTo-SecureString 'synthetic-dummy' -AsPlainText -Force }\nfunction ConvertFrom-SecureString { param($SecureString); 'synthetic-encrypted' }\n& $Script -Name test -BaseUrl https://ha.invalid\n",encoding='utf-8-sig')
            env=os.environ.copy();env['APPDATA']=folder
            result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(driver),'-Script',str(script)],env=env,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            items=json.loads(config.read_text(encoding='utf-8-sig'))['instances']
            self.assertEqual(len(items),1)
            self.assertEqual(items[0]['tailscale'],route)
            self.assertEqual(items[0]['custom'],'keep')
            self.assertEqual(items[0]['baseUrl'],'https://ha.invalid')
