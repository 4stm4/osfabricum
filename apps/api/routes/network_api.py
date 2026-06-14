"""Network Designer API (M45).

    GET  /v1/network-interface-kinds
    GET  /v1/network-profiles
    POST /v1/network-profiles
    GET  /v1/network-profiles/{profile_id}
    PATCH /v1/network-profiles/{profile_id}
    POST /v1/network-profiles/{profile_id}/interfaces
    POST /v1/network-profiles/{profile_id}/dns
    POST /v1/network-profiles/{profile_id}/routes
    POST /v1/network-profiles/{profile_id}/firewall-rules
    POST /v1/network-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import network as net
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["network"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Interface kinds
# ---------------------------------------------------------------------------


@router.get("/v1/network-interface-kinds")
def list_interface_kinds(req: Request) -> list[dict]:
    return net.list_interface_kinds(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    distribution_id: str | None = None
    hostname: str = "localhost"


class UpdateProfileBody(BaseModel):
    name: str | None = None
    hostname: str | None = None


@router.get("/v1/network-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return net.list_network_profiles(distribution_id, db_url=_db(req))


@router.post("/v1/network-profiles")
def create_profile(body: CreateProfileBody, req: Request, _: WriteAuthDep) -> dict:
    try:
        return net.create_network_profile(
            body.name,
            distribution_id=body.distribution_id,
            hostname=body.hostname,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/network-profiles/{profile_id}")
def get_profile(profile_id: str, req: Request) -> dict:
    try:
        return net.get_network_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/network-profiles/{profile_id}")
def update_profile(
    profile_id: str, body: UpdateProfileBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return net.update_network_profile(
            profile_id, name=body.name, hostname=body.hostname, db_url=_db(req)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


class AddInterfaceBody(BaseModel):
    name: str
    kind: str = "ethernet"
    description: str = ""
    mtu: int | None = None
    mac_address: str | None = None
    is_dhcp4: bool = True
    is_dhcp6: bool = False
    static_addresses: list[str] | None = None
    gateway4: str | None = None
    metric: int | None = None
    parent_name: str | None = None
    vlan_id: int | None = None


@router.post("/v1/network-profiles/{profile_id}/interfaces")
def add_interface(
    profile_id: str, body: AddInterfaceBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return net.add_interface(
            profile_id,
            body.name,
            body.kind,
            description=body.description,
            mtu=body.mtu,
            mac_address=body.mac_address,
            is_dhcp4=body.is_dhcp4,
            is_dhcp6=body.is_dhcp6,
            static_addresses=body.static_addresses,
            gateway4=body.gateway4,
            metric=body.metric,
            parent_name=body.parent_name,
            vlan_id=body.vlan_id,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


class AddDnsBody(BaseModel):
    nameserver: str
    search_domain: str | None = None
    priority: int = 100


@router.post("/v1/network-profiles/{profile_id}/dns")
def add_dns(
    profile_id: str, body: AddDnsBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return net.add_dns_entry(
            profile_id,
            body.nameserver,
            search_domain=body.search_domain,
            priority=body.priority,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already in" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class AddRouteBody(BaseModel):
    destination: str
    gateway: str
    metric: int = 0
    interface_name: str | None = None
    description: str = ""


@router.post("/v1/network-profiles/{profile_id}/routes")
def add_route(
    profile_id: str, body: AddRouteBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return net.add_route(
            profile_id,
            body.destination,
            body.gateway,
            metric=body.metric,
            interface_name=body.interface_name,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already in" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Firewall rules
# ---------------------------------------------------------------------------


class AddFirewallRuleBody(BaseModel):
    chain: str
    protocol: str = "any"
    action: str = "ACCEPT"
    source_cidr: str | None = None
    destination_cidr: str | None = None
    dport: str | None = None
    priority: int = 100
    comment: str | None = None


@router.post("/v1/network-profiles/{profile_id}/firewall-rules")
def add_firewall_rule(
    profile_id: str, body: AddFirewallRuleBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return net.add_firewall_rule(
            profile_id,
            body.chain,
            body.protocol,
            body.action,
            source_cidr=body.source_cidr,
            destination_cidr=body.destination_cidr,
            dport=body.dport,
            priority=body.priority,
            comment=body.comment,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 400 if "unknown" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/network-profiles/{profile_id}/render")
def render(profile_id: str, req: Request, _: WriteAuthDep) -> dict:
    try:
        return net.render_network_config(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
