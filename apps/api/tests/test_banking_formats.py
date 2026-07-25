from tests.conftest import register_and_login

BANK = "/api/v1/banking"

MT940 = """:20:STMT
:25:BG80BNBG96611020345678
:60F:C260701EUR1000,00
:61:2607150715C1000,00NTRFINV-1//R1
:86:Плащане по фактура INV-1
:61:2607160716D250,00NTRFSUP-1
:86:Плащане към доставчик
:62F:C260716EUR1750,00
"""

CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
 <BkToCstmrStmt><Stmt>
  <Ntry><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <BookgDt><Dt>2026-07-15</Dt></BookgDt>
    <NtryDtls><TxDtls><RmtInf><Ustrd>Плащане INV-1</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
  <Ntry><Amt Ccy="EUR">250.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
    <BookgDt><Dt>2026-07-16</Dt></BookgDt></Ntry>
 </Stmt></BkToCstmrStmt>
</Document>
"""


def _setup(client, email):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    acc_id = client.post(f"{BANK}/accounts", headers=h, json={"name": "Разпл."}).json()["id"]
    return h, acc_id


def test_mt940_import(client):
    h, acc_id = _setup(client, "mt1@example.com")
    r = client.post(f"{BANK}/accounts/{acc_id}/import-mt940", headers=h,
                    files={"file": ("stmt.sta", MT940.encode("utf-8"), "text/plain")})
    assert r.status_code == 201, r.text
    assert r.json() == {"imported": 2, "duplicates": 0}
    txs = client.get(f"{BANK}/transactions", headers=h).json()
    assert sorted(float(t["amount"]) for t in txs) == [-250.0, 1000.0]
    # дедупликация
    r2 = client.post(f"{BANK}/accounts/{acc_id}/import-mt940", headers=h,
                     files={"file": ("stmt.sta", MT940.encode("utf-8"), "text/plain")})
    assert r2.json()["duplicates"] == 2


def test_camt_import(client):
    h, acc_id = _setup(client, "camt1@example.com")
    r = client.post(f"{BANK}/accounts/{acc_id}/import-camt", headers=h,
                    files={"file": ("stmt.xml", CAMT.encode("utf-8"), "application/xml")})
    assert r.status_code == 201, r.text
    assert r.json() == {"imported": 2, "duplicates": 0}
    txs = client.get(f"{BANK}/transactions", headers=h).json()
    assert sorted(float(t["amount"]) for t in txs) == [-250.0, 1000.0]


def test_camt_with_entity_declarations_is_rejected(client):
    """Качен XML с ENTITY декларации („billion laughs") се отказва, а не се разгъва."""
    h, acc_id = _setup(client, "camt-bomb@example.com")
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">\n'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>\n'
        b'<Document><Ntry><Amt Ccy="EUR">&lol3;</Amt></Ntry></Document>'
    )
    r = client.post(f"{BANK}/accounts/{acc_id}/import-camt", headers=h,
                    files={"file": ("bomb.xml", bomb, "application/xml")})
    assert r.status_code == 422
    assert "Отказан CAMT XML" in r.json()["detail"]
    assert client.get(f"{BANK}/transactions", headers=h).json() == []


def test_mt940_empty_rejected(client):
    h, acc_id = _setup(client, "mt2@example.com")
    r = client.post(f"{BANK}/accounts/{acc_id}/import-mt940", headers=h,
                    files={"file": ("x.sta", b":20:STMT\n:25:ACC\n", "text/plain")})
    assert r.status_code == 422
