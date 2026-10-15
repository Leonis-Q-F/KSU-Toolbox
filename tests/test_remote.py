import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from firmware import RemoteFile, ToolError

class Response:
    def __init__(self,body,headers,status=206):
        self.raw=io.BytesIO(body);self.headers=headers;self.status_code=status
    def __enter__(self):return self
    def __exit__(self,*args):pass

class HTTP:
    def __init__(self,broken=None):
        self.body=b'PK'+bytes(range(256))*3000
        self.broken=broken;self.requests=0
    def mount(self,*args):pass
    def close(self):pass
    def get(self,url,headers,**kwargs):
        self.requests+=1
        a,b=map(int,headers['Range'][6:].split('-'))
        response_headers={'Content-Range':f'bytes {a}-{b}/{len(self.body)}','ETag':'"one"'}
        if self.requests>1:
            if self.broken=='changed':response_headers['ETag']='"two"'
            if self.broken=='wrong-range':response_headers['Content-Range']='bytes 1-2/3'
            if self.broken=='ignored':return Response(self.body,response_headers,200)
        return Response(self.body[a:b+1],response_headers)

class RemoteTests(unittest.TestCase):
    def test_seeks_across_block_boundary_without_full_download(self):
        http=HTTP()
        with patch('firmware.requests.Session',return_value=http):
            with RemoteFile('https://example.test/ota.zip') as file:
                file.seek(262140)
                self.assertEqual(file.read(10),http.body[262140:262150])
                file.seek(-16,2)
                self.assertEqual(file.read(16),http.body[-16:])
                self.assertLessEqual(file.downloaded,len(http.body)+1)
    def test_changed_remote_file_rejected(self):
        with patch('firmware.requests.Session',return_value=HTTP('changed')):
            with RemoteFile('https://example.test/ota.zip') as file:
                with self.assertRaises(ToolError):file.read(16)
    def test_ignored_range_rejected_before_reading_body(self):
        with patch('firmware.requests.Session',return_value=HTTP('ignored')):
            with RemoteFile('https://example.test/ota.zip') as file:
                with self.assertRaises(ToolError):file.read(16)
    def test_wrong_content_range_rejected(self):
        with patch('firmware.requests.Session',return_value=HTTP('wrong-range')):
            with RemoteFile('https://example.test/ota.zip') as file:
                with self.assertRaises(ToolError):file.read(16)

if __name__=='__main__':unittest.main()
