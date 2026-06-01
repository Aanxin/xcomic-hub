import subprocess
import json as _json
import base64


def urlopen_native(url, data=None, headers=None, timeout=15):
    data_b64 = base64.b64encode(data).decode('ascii') if data else None
    req_info = {
        'url': url,
        'data_b64': data_b64,
        'headers': dict(headers) if headers else {},
        'timeout': timeout
    }
    script = (
        "import http.client,json,sys,ssl,base64\n"
        "from urllib.parse import urlparse\n"
        "try:\n"
        "  a=json.loads(sys.argv[1])\n"
        "  p=urlparse(a['url'])\n"
        "  h=p.hostname\n"
        "  pt=p.port or (443 if p.scheme=='https' else 80)\n"
        "  path=p.path or '/'\n"
        "  if p.query:path+='?'+p.query\n"
        "  if p.scheme=='https':\n"
        "    ctx=ssl.create_default_context()\n"
        "    c=http.client.HTTPSConnection(h,pt,context=ctx,timeout=a['timeout'])\n"
        "  else:\n"
        "    c=http.client.HTTPConnection(h,pt,timeout=a['timeout'])\n"
        "  m='POST' if a['data_b64'] else 'GET'\n"
        "  hdrs=a['headers']\n"
        "  if 'Host' not in hdrs:hdrs['Host']=h if pt in(80,443)else f'{h}:{pt}'\n"
        "  body=base64.b64decode(a['data_b64']) if a['data_b64'] else None\n"
        "  c.request(m,path,body=body,headers=hdrs)\n"
        "  r=c.getresponse()\n"
        "  rbody=r.read().decode('utf-8','ignore')\n"
        "  hdrs_list=r.getheaders()\n"
        "  set_cookie=r.getheader('Set-Cookie','')\n"
        "  result={'status':r.status,'body':rbody,'headers':dict(hdrs_list),'set_cookie':set_cookie}\n"
        "  print(json.dumps(result))\n"
        "except TimeoutError:\n"
        "  print(json.dumps({'error':'timeout'}))\n"
        "except ConnectionRefusedError:\n"
        "  print(json.dumps({'error':'connection_refused'}))\n"
        "except Exception as e:\n"
        "  print(json.dumps({'error':str(e)}))\n"
    )
    try:
        result = subprocess.run(
            ['python', '-c', script, _json.dumps(req_info)],
            capture_output=True, text=True, timeout=timeout + 15
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if 'No module named' in stderr or 'ImportError' in stderr:
                result2 = subprocess.run(
                    ['python3', '-c', script, _json.dumps(req_info)],
                    capture_output=True, text=True, timeout=timeout + 15
                )
                if result2.returncode != 0:
                    raise Exception(result2.stderr.strip() or f'子进程退出码 {result2.returncode}')
                resp_data = _json.loads(result2.stdout.strip())
            else:
                raise Exception(stderr or f'子进程退出码 {result.returncode}')
        else:
            resp_data = _json.loads(result.stdout.strip())
        if 'error' in resp_data:
            err = resp_data['error']
            if err == 'timeout':
                raise Exception(f'请求超时 ({timeout}s)')
            elif err == 'connection_refused':
                raise Exception('连接被拒绝')
            else:
                raise Exception(err)
        return resp_data
    except subprocess.TimeoutExpired:
        raise Exception(f'请求超时 ({timeout}s)')
    except _json.JSONDecodeError:
        raise Exception(f'解析响应失败: {result.stdout[:200] if result else "N/A"}')
