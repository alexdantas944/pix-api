from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import segno
import base64
import uuid
import os
import asyncio
import httpx
from unidecode import unidecode
from io import BytesIO
from typing import Optional

app = FastAPI(title="API Pix Pixels")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONEXÕES ---
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
# Usando o nome que você definiu no Render
URL_AUTO = os.environ.get("URL_automatica")

if not URL or not KEY:
    print("ERRO: SUPABASE_URL ou SUPABASE_KEY ausentes!")
    supabase = None
else:
    supabase: Client = create_client(URL, KEY)

# --- SISTEMA PARA MANTER ACORDADO ---
async def keep_awake_task():
    """ Loop que roda em paralelo para evitar o sleep do Render """
    # Espera 30 segundos antes do primeiro ping para o servidor subir 100%
    await asyncio.sleep(30)
    
    while True:
        if URL_AUTO:
            try:
                # Timeout curto para não travar nada
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{URL_AUTO}/ping")
                    print(f" LOG: Self-ping enviado para {URL_AUTO}. Status: {response.status_code}")
            except Exception as e:
                print(f" LOG: Erro no self-ping (normal se estiver iniciando): {e}")
        else:
            print(" LOG: URL_automatica não configurada nas variáveis de ambiente.")
        
        # Espera 10 minutos para o próximo
        await asyncio.sleep(600)

@app.on_event("startup")
async def startup_event():
    # Isso cria a tarefa sem bloquear a inicialização da API
    asyncio.create_task(keep_awake_task())

# --- MODELOS ---
class PixRequest(BaseModel):
    chave: str
    nome: str
    cidade: str
    valor: float
    txid: Optional[str] = "WEBPIX"

# --- LÓGICA PIX ---
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

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"status": "online", "message": "API Pix ativa"}

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.post("/api/v1/pix")
async def criar_pix(request: PixRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    
    id_venda = str(uuid.uuid4())[:8]
    payload_pix = PixService.gerar(request)
    
    try:
        supabase.table("transacoes").insert({
            "id": id_venda, "valor": request.valor,
            "txid": request.txid, "status": "PENDENTE"
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro banco: {e}")

    qr = segno.make(payload_pix, error='M')
    buffer = BytesIO()
    qr.save(buffer, kind='png', scale=10)
    qr_base64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    
    return {"id_transacao": id_venda, "payload": payload_pix, "qrcode_base64": qr_base64}

@app.get("/api/v1/status/{id_transacao}")
async def checar_status(id_transacao: str):
    res = supabase.table("transacoes").select("status").eq("id", id_transacao).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Não encontrado")
    return {"status": res.data[0]["status"]}

@app.get("/api/v1/admin/todas")
async def listar_todas():
    res = supabase.table("transacoes").select("*").order("created_at", desc=True).limit(20).execute()
    return res.data

@app.get("/api/v1/admin/confirmar/{id_transacao}")
async def confirmar_pagamento(id_transacao: str):
    supabase.table("transacoes").update({"status": "PAGO"}).eq("id", id_transacao).execute()
    return {"message": "OK"}
