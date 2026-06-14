"""License / SBOM / Vuln / Source Compliance Designer API (M48).

    GET  /v1/spdx-license-kinds
    GET  /v1/compliance-profiles
    POST /v1/compliance-profiles
    GET  /v1/compliance-profiles/{profile_id}
    PATCH /v1/compliance-profiles/{profile_id}
    POST /v1/compliance-profiles/{profile_id}/license-rules
    GET  /v1/compliance-profiles/{profile_id}/license-rules
    POST /v1/compliance-profiles/{profile_id}/vuln-gates
    GET  /v1/compliance-profiles/{profile_id}/vuln-gates
    POST /v1/compliance-profiles/{profile_id}/sbom-entries
    GET  /v1/compliance-profiles/{profile_id}/sbom-entries
    POST /v1/compliance-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import compliance as cmp
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["compliance"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _profile_dict(p: object) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "description": p.description,
        "allow_copyleft": p.allow_copyleft,
        "allow_proprietary": p.allow_proprietary,
        "min_vuln_severity_to_block": p.min_vuln_severity_to_block,
        "require_sbom": p.require_sbom,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# SPDX license kinds
# ---------------------------------------------------------------------------


@router.get("/v1/spdx-license-kinds")
def list_spdx_license_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        return [
            {
                "spdx_id": k.spdx_id,
                "name": k.name,
                "is_copyleft": k.is_copyleft,
                "is_permissive": k.is_permissive,
                "display_order": k.display_order,
            }
            for k in cmp.list_spdx_license_kinds(s)
        ]


# ---------------------------------------------------------------------------
# Compliance profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    distribution_id: str | None = None
    description: str = ""
    allow_copyleft: bool = True
    allow_proprietary: bool = False
    min_vuln_severity_to_block: str = "critical"
    require_sbom: bool = True


class UpdateProfileBody(BaseModel):
    name: str | None = None
    description: str | None = None
    allow_copyleft: bool | None = None
    allow_proprietary: bool | None = None
    min_vuln_severity_to_block: str | None = None
    require_sbom: bool | None = None


@router.get("/v1/compliance-profiles")
def list_compliance_profiles(
    req: Request, distribution_id: str | None = None
) -> list[dict]:
    with sync_session(_db(req)) as s:
        return [_profile_dict(p) for p in cmp.list_compliance_profiles(s, distribution_id)]


@router.post("/v1/compliance-profiles")
def create_compliance_profile(
    body: CreateProfileBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = cmp.create_compliance_profile(
                s,
                name=body.name,
                distribution_id=body.distribution_id,
                description=body.description,
                allow_copyleft=body.allow_copyleft,
                allow_proprietary=body.allow_proprietary,
                min_vuln_severity_to_block=body.min_vuln_severity_to_block,
                require_sbom=body.require_sbom,
            )
            s.commit()
            return _profile_dict(p)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/compliance-profiles/{profile_id}")
def get_compliance_profile(profile_id: str, req: Request) -> dict:
    with sync_session(_db(req)) as s:
        try:
            return _profile_dict(cmp.get_compliance_profile(s, profile_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/compliance-profiles/{profile_id}")
def update_compliance_profile(
    profile_id: str, body: UpdateProfileBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    with sync_session(_db(req)) as s:
        try:
            p = cmp.update_compliance_profile(s, profile_id, **updates)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# License rules
# ---------------------------------------------------------------------------


class LicenseRuleBody(BaseModel):
    spdx_id: str
    policy: str
    reason: str | None = None


@router.post("/v1/compliance-profiles/{profile_id}/license-rules")
def set_license_rule(
    profile_id: str,
    body: LicenseRuleBody,
    req: Request,
    _auth: WriteAuthDep = None,
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = cmp.set_license_rule(
                s, profile_id, body.spdx_id, body.policy, body.reason
            )
            s.commit()
            return {
                "id": r.id, "profile_id": r.profile_id,
                "spdx_id": r.spdx_id, "policy": r.policy, "reason": r.reason,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/compliance-profiles/{profile_id}/license-rules")
def list_license_rules(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": r.id, "profile_id": r.profile_id,
                    "spdx_id": r.spdx_id, "policy": r.policy, "reason": r.reason,
                }
                for r in cmp.list_license_rules(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Vuln gates
# ---------------------------------------------------------------------------


class VulnGateBody(BaseModel):
    cve_id: str
    severity: str
    action: str
    package_name: str | None = None
    affected_version: str | None = None
    reason: str | None = None


@router.post("/v1/compliance-profiles/{profile_id}/vuln-gates")
def set_vuln_gate(
    profile_id: str,
    body: VulnGateBody,
    req: Request,
    _auth: WriteAuthDep = None,
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            g = cmp.set_vuln_gate(
                s, profile_id, body.cve_id, body.severity, body.action,
                body.package_name, body.affected_version, body.reason,
            )
            s.commit()
            return {
                "id": g.id, "profile_id": g.profile_id, "cve_id": g.cve_id,
                "severity": g.severity, "action": g.action,
                "package_name": g.package_name,
                "affected_version": g.affected_version, "reason": g.reason,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/compliance-profiles/{profile_id}/vuln-gates")
def list_vuln_gates(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": g.id, "profile_id": g.profile_id, "cve_id": g.cve_id,
                    "severity": g.severity, "action": g.action,
                    "package_name": g.package_name,
                    "affected_version": g.affected_version, "reason": g.reason,
                }
                for g in cmp.list_vuln_gates(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# SBOM entries
# ---------------------------------------------------------------------------


class SbomEntryBody(BaseModel):
    package_name: str
    package_version: str
    spdx_id: str | None = None
    purl: str | None = None
    supplier: str | None = None
    source_url: str | None = None
    is_source_available: bool = True


@router.post("/v1/compliance-profiles/{profile_id}/sbom-entries")
def add_sbom_entry(
    profile_id: str,
    body: SbomEntryBody,
    req: Request,
    _auth: WriteAuthDep = None,
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            e = cmp.add_sbom_entry(
                s, profile_id, body.package_name, body.package_version,
                body.spdx_id, body.purl, body.supplier,
                body.source_url, body.is_source_available,
            )
            s.commit()
            return {
                "id": e.id, "profile_id": e.profile_id,
                "package_name": e.package_name, "package_version": e.package_version,
                "spdx_id": e.spdx_id, "purl": e.purl,
                "supplier": e.supplier, "source_url": e.source_url,
                "is_source_available": e.is_source_available,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/compliance-profiles/{profile_id}/sbom-entries")
def list_sbom_entries(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": e.id, "profile_id": e.profile_id,
                    "package_name": e.package_name,
                    "package_version": e.package_version,
                    "spdx_id": e.spdx_id, "purl": e.purl,
                    "supplier": e.supplier, "source_url": e.source_url,
                    "is_source_available": e.is_source_available,
                }
                for e in cmp.list_sbom_entries(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/compliance-profiles/{profile_id}/render")
def render_compliance_report(
    profile_id: str, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = cmp.render_compliance_report(s, profile_id)
            s.commit()
            return {
                "id": p.id,
                "content_hash": p.content_hash,
                "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
                "rendered_sbom": p.rendered_sbom,
                "rendered_vuln_report": p.rendered_vuln_report,
                "rendered_license_report": p.rendered_license_report,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
