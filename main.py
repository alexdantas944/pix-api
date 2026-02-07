from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import segno, base64, uuid, os
from unidecode import unidecode
from io import BytesIO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURAÇÃO SUPABASE ---
# No Render, você vai adicionar essas duas como Variáveis de Ambiente
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class PixRequest(BaseModel):
    chave: str
    nome: str
    cidade: str
    valor: float
    txid: str = "LOJA01"

class PixService:
    @staticmethod
    def _crc16(payload: str) -> str:
        crc = 0xFFFF
        for byte in payload.encode('utf-8'):
            crc ^= (byte << 8)
            for _ in range(8):
                crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else crc << 1
        return hex(crc & 0xFFFF)[2:].upper().zfill(4)

    @classmethod
    def gerar(cls, d: PixRequest):
        def f(id, v): return f"{id}{len(v):02}{v}"
        campos = [
            f("00", "01"),
            f("26", f("00", "br.gov.bcb.pix") + f("01", d.chave)),
            f("52", "0000"), f("53", "986"),
            f("54", f"{d.valor:.2f}"), f("58", "BR"),
            f("59", unidecode(d.nome).upper()[:25]),
            f("60", unidecode(d.cidade).upper()[:15]),
            f("62", f("05", d.txid[:25])), "6304"
        ]
        pre = "".join(campos)
        return pre + cls._crc16(pre)

@app.post("/api/v1/pix")
async def criar_pix(request: PixRequest):
    id_venda = str(uuid.uuid4())[:8]
    payload = PixService.gerar(request)
    
    # Salva no Supabase
    data = {
        "id": id_venda,
        "valor": request.valor,
        "txid": request.txid,
        "status": "PENDENTE"
    }
    supabase.table("transacoes").insert(data).execute()

    qr = segno.make(payload, error='M')
    buffer = BytesIO()
    qr.save(buffer, kind='png', scale=10)
    
    return {
        "id_transacao": id_venda,
        "payload": payload,
        "qrcode_base64": f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    }

@app.get("/api/v1/status/{id_transacao}")
def checar_status(id_transacao: str):
    response = supabase.table("transacoes").select("status").eq("id", id_transacao).execute()
    if not response.data:
        raise HTTPException(404, "Não encontrado")
    return {"status": response.data[0]["status"]}

@app.get("/api/v1/admin/confirmar/{id_transacao}")
def confirmar_admin(id_transacao: str):
    supabase.table("transacoes").update({"status": "PAGO"}).eq("id", id_transacao).execute()
    return {"message": "Pagamento confirmado via Supabase!"}
