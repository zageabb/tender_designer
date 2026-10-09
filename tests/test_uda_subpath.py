"""UDA reverse proxy and LAN route compatibility tests."""
from app import app

def test_uda_login_assets_and_root_redirect():
    client=app.test_client()
    local=client.get("/auth/login")
    assert local.status_code==200
    assert '<base href="/">' in local.get_data(as_text=True)
    local_cookie=local.headers["Set-Cookie"]
    assert local_cookie.startswith("tender_designer_session=")
    assert "Path=/;" in local_cookie
    headers={
        "X-Forwarded-Prefix":"/apps/tender-designer",
        "X-Forwarded-Host":"tanyaanne.ddns.net",
        "X-Forwarded-Proto":"https",
    }
    proxied=client.get("/auth/login",headers=headers)
    assert proxied.status_code==200
    html=proxied.get_data(as_text=True)
    assert '<base href="/apps/tender-designer/">' in html
    assert '/apps/tender-designer/static/css/app.css' in html
    proxied_cookie=proxied.headers["Set-Cookie"]
    assert proxied_cookie.startswith("tender_designer_session=")
    assert "Path=/apps/tender-designer/;" in proxied_cookie
    assert "; Secure;" in proxied_cookie
    root=client.get("/",headers=headers,follow_redirects=False)
    assert root.status_code in (301,302,303,307,308)
    assert "/apps/tender-designer/auth/login" in root.headers["Location"]
