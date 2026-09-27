from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.authenticity import router as authenticity_router
from app.api.routes.health import router as health_router
from app.api.routes.identity import router as identity_router
from app.api.routes.inventory import router as inventory_router
from app.api.routes.me import router as me_router
from app.api.routes.proof import router as proof_router
from app.api.routes.registry import router as registry_router
from app.api.routes.shopify import router as shopify_router
from app.api.routes.public_proof import router as public_proof_router
from app.api.routes.public_registration import router as public_registration_router
from app.api.routes.public_verification import router as public_verification_router
from app.api.routes.warranty import router as warranty_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS", "PUT"],
    allow_headers=["Accept", "Content-Type", "Authorization", "Idempotency-Key", "X-Proof-Upload-Grant"],
)

app.include_router(health_router)
app.include_router(authenticity_router)
app.include_router(me_router)
app.include_router(identity_router)
app.include_router(inventory_router)
app.include_router(public_verification_router)
app.include_router(public_registration_router)
app.include_router(public_proof_router)
app.include_router(proof_router)
app.include_router(registry_router)
app.include_router(shopify_router)
app.include_router(warranty_router)
