import os
import sys

# Os testes rodam contra SQLite de forma EXPLÍCITA. Sem esta flag, conectar()
# falha (fail-closed) e não cai silenciosamente no SQLite — comportamento que
# evita "split-brain" (dados indo para um banco diferente do de produção).
os.environ.setdefault("PONTO_ALLOW_SQLITE", "1")

# O caminho do SQLite precisa bater com o app.DB (BASE/ponto.db) usado pelo
# test_hash_nao_e_texto_puro; fora do servidor /opt/ponto não existe, então
# aponta para o ponto.db do próprio projeto.
os.environ.setdefault("PONTO_SQLITE_PATH",
                      os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "ponto.db"))

# Senha do admin usada nos testes de login (deve casar com a ADMIN_SENHA do
# test_auth.py). O fallback de produção fica em PONTO_ADMIN_SENHA no service.
os.environ.setdefault("PONTO_ADMIN_SENHA", "jteI0p4anqBW9UgG")

# Segredo JWT aleatório por execução (sem isto o auth.py tentaria gravar em
# /opt/ponto/jwt-secret.txt, que não existe fora do servidor).
os.environ.setdefault("PONTO_JWT_SECRET", __import__("secrets").token_hex(32))

# Em produção o lifespan do app cria schema + admin no startup; o TestClient não
# dispara lifespan, então a suíte faz o bootstrap antes dos testes de API.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import garantir_admin  # noqa: E402
from db import conectar, criar_schema  # noqa: E402

_con = conectar()
try:
    criar_schema(_con)
    garantir_admin(_con)
finally:
    _con.close()
