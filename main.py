from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
import segno
from unidecode import unidecode
from io import BytesIO
import base64

app = FastAPI(
    title="API Pix Generator Robust",
    description="Gera payloads EMV QRCPS (Pix Copia e Cola) e QR Codes em Base64.",
    version="1.0.0"
)

# --- MODELO DE DADOS COM VALIDAÇÃO ---
class PixRequest(BaseModel):
    chave: str = Field(..., description="Chave Pix (CPF, Email, Tel ou Aleatória)", min_length=1)
    nome: str = Field(..., description="Nome do beneficiário", max_length=25)
    cidade: str = Field(..., description="Cidade do beneficiário", max_length=15)
    txid: str = Field("***", description="Identificador da transação (opcional)", max_length=25)
    valor: float = Field(None, description="Valor da transação (opcional)", ge=0.01)

    # Sanitização automática: Remove acentos e força maiúsculas
    @field_validator('nome', 'cidade')
    def sanitizar_texto(cls, v):
        # Transforma "São Paulo" em "SAO PAULO"
        return unidecode(v).upper()

# --- LÓGICA DE NEGÓCIO (CORE) ---
class PixService:
    @staticmethod
    def _crc16_ccitt(payload: str) -> str:
        """Calcula o CRC-16-CCITT (0x1021) sem dependências externas."""
        crc = 0xFFFF
        polynomial = 0x1021
        encoded = payload.encode('utf-8')
        
        for byte in encoded:
            crc ^= (byte << 8)
            for _ in range(8):
                if (crc & 0x8000):
                    crc = (crc << 1) ^ polynomial
                else:
                    crc = crc << 1
        
        return hex(crc & 0xFFFF)[2:].upper().zfill(4)

    @staticmethod
    def _formatar(id_campo: str, valor: str) -> str:
        return f"{id_campo}{len(valor):02}{valor}"

    @classmethod
    def gerar_payload(cls, dados: PixRequest) -> str:
        # Payload Basico
        payload = [
            cls._formatar("00", "01"),  # Payload Format Indicator
            cls._formatar("26", cls._formatar("00", "br.gov.bcb.pix") + cls._formatar("01", dados.chave)),
            cls._formatar("52", "0000"), # Merchant Category Code
            cls._formatar("53", "986"),  # Moeda (BRL)
        ]

        if dados.valor:
            payload.append(cls._formatar("54", f"{dados.valor:.2f}"))

        payload.extend([
            cls._formatar("58", "BR"),
            cls._formatar("59", dados.nome), # Já sanitizado pelo Pydantic
            cls._formatar("60", dados.cidade), # Já sanitizado
            cls._formatar("62", cls._formatar("05", dados.txid)),
            "6304" # Placeholder para o CRC
        ])

        payload_str = "".join(payload)
        crc = cls._crc16_ccitt(payload_str)
        return payload_str + crc

    @staticmethod
    def gerar_qrcode_base64(payload_pix: str) -> str:
        """Gera o QR Code e retorna em Base64 para uso direto em tags <img>"""
        try:
            # Cria o QR Code com a lib Segno (Micro QR automático se possível)
            qr = segno.make(payload_pix, error='M') 
            
            # Salva em buffer de memória
            buffer = BytesIO()
            qr.save(buffer, kind='png', scale=5)
            
            # Converte para base64
            b64_img = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return f"data:image/png;base64,{b64_img}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao gerar imagem QR: {str(e)}")

# --- ENDPOINTS ---
@app.post("/api/v1/pix", tags=["Pix"])
def criar_pix(request: PixRequest):
    # 1. Gera a string Copia e Cola
    pix_string = PixService.gerar_payload(request)
    
    # 2. Gera a imagem Base64
    qr_image = PixService.gerar_qrcode_base64(pix_string)
    
    return {
        "status": "success",
        "data": {
            "payload": pix_string,
            "qrcode_base64": qr_image,
            "mensagem": "Use o campo 'qrcode_base64' dentro de <img src='...'> no HTML"
        }
    }

# Entrypoint para debug
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

