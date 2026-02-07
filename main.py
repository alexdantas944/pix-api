from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import segno
from unidecode import unidecode
from io import BytesIO
import base64

# --- INICIALIZAÇÃO DA API ---
app = FastAPI(
    title="API Pix Robusta",
    description="Geração de Pix Estático com QR Code e suporte a CORS",
    version="1.1.0"
)

# --- CONFIGURAÇÃO DE CORS ---
# Isso permite que seu site de doação (ou qualquer outro) acesse a API sem ser bloqueado
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELO DE DADOS (VALIDAÇÃO) ---
class PixRequest(BaseModel):
    chave: str = Field(..., min_length=1)
    nome: str = Field(..., max_length=25)
    cidade: str = Field(..., max_length=15)
    txid: str = Field("***", max_length=25)
    valor: float = Field(None, ge=0.01)

    @field_validator('nome', 'cidade')
    @classmethod
    def limpar_texto(cls, v):
        # Remove acentos e força maiúsculas para o padrão do Banco Central
        return unidecode(v).upper()

# --- SERVIÇO CORE (LÓGICA PIX) ---
class PixService:
    @staticmethod
    def _crc16_ccitt(payload: str) -> str:
        crc = 0xFFFF
        polynomial = 0x1021
        for byte in payload.encode('utf-8'):
            crc ^= (byte << 8)
            for _ in range(8):
                if (crc & 0x8000):
                    crc = (crc << 1) ^ polynomial
                else:
                    crc = crc << 1
        return hex(crc & 0xFFFF)[2:].upper().zfill(4)

    @staticmethod
    def _format(id, valor):
        return f"{id}{len(valor):02}{valor}"

    @classmethod
    def gerar_payload(cls, d: PixRequest) -> str:
        # Montagem dos campos padrão EMV
        campos = [
            cls._format("00", "01"),
            cls._format("26", cls._format("00", "br.gov.bcb.pix") + cls._format("01", d.chave)),
            cls._format("52", "0000"),
            cls._format("53", "986"),
        ]
        
        if d.valor:
            campos.append(cls._format("54", f"{d.valor:.2f}"))
        
        campos.extend([
            cls._format("58", "BR"),
            cls._format("59", d.nome),
            cls._format("60", d.cidade),
            cls._format("62", cls._format("05", d.txid)),
            "6304" # ID do CRC
        ])

        payload_parcial = "".join(campos)
        return payload_parcial + cls._crc16_ccitt(payload_parcial)

# --- ENDPOINT PRINCIPAL ---
@app.post("/api/v1/pix")
async def criar_pix(request: PixRequest):
    try:
        # 1. Gerar a string Pix Copia e Cola
        payload = PixService.gerar_payload(request)
        
        # 2. Gerar o QR Code em Base64
        qr = segno.make(payload, error='M')
        buffer = BytesIO()
        qr.save(buffer, kind='png', scale=10)
        qr_base64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
        
        return {
            "status": "success",
            "data": {
                "payload": payload,
                "qrcode_base64": qr_base64
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

# Endpoint de saúde para o Render não derrubar a API
@app.get("/")
def health_check():
    return {"status": "online", "message": "API Pix ativa"}
