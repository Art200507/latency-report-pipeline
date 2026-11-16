import importlib.util
from pathlib import Path
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
spec=importlib.util.spec_from_file_location('access',Path(__file__).resolve().parents[1]/'api/access.py')
access=importlib.util.module_from_spec(spec);spec.loader.exec_module(access)
app=FastAPI()
@app.post('/api/run',dependencies=[Depends(access.require_operator)])
def run():return {'started':True}
class AccessTests(unittest.TestCase):
 def test_publishing_is_closed_by_default(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(TestClient(app).post('/api/run').status_code,503)
 def test_token_required(self):
  with patch.dict(os.environ,{'OPERATOR_API_TOKEN':'test-operator'},clear=True):
   client=TestClient(app)
   for headers in [{},{'Authorization':'Bearer wrong'}]:self.assertEqual(client.post('/api/run',headers=headers).status_code,401)
   self.assertEqual(client.post('/api/run',headers={'Authorization':'Bearer test-operator'}).status_code,200)
if __name__=='__main__':unittest.main()
