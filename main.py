from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import segno
import base64
import uuid
import os
import asyncio  # Importado para o timer
import httpx    # Importado para fazer a requisição de ping (equivalente ao axios)
from unidecode import unidecode
from io import BytesIO
from typing import Optional

# --- INICIALIZAÇÃO ---
app = FastAPI(title="API Pix Pixels - Supabase Edition")

# --- CONFIGURAÇÃO DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONEXÃO SUPABASE ---
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
# Recomendo criar uma variável de ambiente chamada SELF_URL no Render 
# com o endereço da sua própria API (ex: https://sua-api.onrender.com)
SELF_URL = os.environ.get("SELF_URL")

if not URL or not KEY:
    print("ERRO CRÍTICO: Variáveis SUPABASE_URL ou SUPABASE_KEY não configuradas!")
    supabase = None
else:
    supabase: Client = create_client(URL, KEY)

# --- LÓGICA PARA MANTER A API ACORDADA (SELF-PING) ---
async def keep_awake():
    """
    Faz uma requisição para si mesmo a cada 10 minutos para evitar o sleep do Render.
    """
    await asyncio.sleep(5) # Espera 5 segundos após iniciar
    while True:
        if SELF_URL:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{SELF_URL}/ping")
                    print(f"Self-ping efetuado: {response.status_code}")
            except Exception as e:
                print(f"Erro no self-ping: {e}")
        else:
            print("Aviso: SELF_URL não configurada. O self-ping não funcionará.")
        
        await asyncio.sleep(600) # 600 segundos = 10 minutos

@app.on_event("startup")
async def startup_event():
    # Inicia a tarefa de manter acordado em segundo plano
    asyncio.create_task(keep_awake())

# --- MODELOS DE DADOS ---
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
            f("52", "0000"),
            f("53", "986"),
            f("54", f"{d.valor:.2f}"),
            f("58", "BR"),
            f("59", unidecode(d.nome).upper()[:25]),
            f("60", unidecode(d.cidade).upper()[:15]),
            f("62", f("05", d.txid[:25])),
            "6304"
        ]
        
        pre_payload = "".join(campos)
        return pre_payload + cls._crc16(pre_payload)

# --- ENDPOINTS ---

@app.get("/")
def health_check():
    status = "conectado" if supabase else "sem_banco_de_dados"
    return {"status": "online", "supabase": status}

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.post("/api/v1/pix")
async def criar_pix(request: PixRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Banco de dados não configurado.")

    id_venda = str(uuid.uuid4())[:8]
    payload_pix = PixService.gerar(request)
    
    try:
        data = {
            "id": id_venda,
            "valor": request.valor,
            "txid": request.txid,
            "status": "PENDENTE"
        }
        supabase.table("transacoes").insert(data).execute()
    except Exception as e:
        print(f"Erro Supabase: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar no banco.")

    qr = segno.make(payload_pix, error='M')
    buffer = BytesIO()
    qr.save(buffer, kind='png', scale=10)
    qr_base64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    
    return {
        "id_transacao": id_venda,
        "payload": payload_pix,
        "qrcode_base64": qr_base64
    }

@app.get("/api/v1/status/{id_transacao}")
async def checar_status(id_transacao: str):
    response = supabase.table("transacoes").select("status").eq("id", id_transacao).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    return {"status": response.data[0]["status"]}

# --- ENDPOINTS ADMIN ---

@app.get("/api/v1/admin/todas")
async def listar_todas():
    response = supabase.table("transacoes").select("*").order("created_at", desc=True).limit(20).execute()
    return response.data

@app.get("/api/v1/admin/confirmar/{id_transacao}")
async def confirmar_pagamento(id_transacao: str):
    supabase.table("transacoes").update({"status": "PAGO"}).eq("id", id_transacao).execute()
    return {"message": "Pagamento confirmado com sucesso!"}
