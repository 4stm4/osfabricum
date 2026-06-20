"""Reference distribution query service (Phase 5 — M71/M72/M73).

Provides read-only query helpers over the seeded reference distributions.
Each function is stateless, idempotent, and takes an open SQLAlchemy session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    Architecture,
    Board,
    Distribution,
    DistributionClass,
    Kernel,
    Package,
    PackageGroup,
    PackageGroupMember,
    PackageSet,
    PackageSetMember,
    Profile,
    Toolchain,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class RefDistSummary:
    id: str
    name: str
    description: str | None
    class_name: str | None
    default_channel: str | None
    profiles: list[str] = field(default_factory=list)
    package_count: int = 0
    group_count: int = 0
    set_count: int = 0


@dataclass
class RefDistProfile:
    id: str
    name: str
    distribution_id: str
    board_name: str | None
    arch_name: str | None
    kernel_name: str | None
    toolchain_name: str | None
    package_set_name: str | None
    packages: list[str] = field(default_factory=list)


REFERENCE_DIST_NAMES = ("tinywifi", "netos", "ocultum")


def list_reference_distributions(session: "Session") -> list[RefDistSummary]:
    """Return summary records for all known reference distributions."""
    class_map = {c.id: c.name for c in session.scalars(select(DistributionClass)).all()}
    summaries: list[RefDistSummary] = []
    for dist_name in REFERENCE_DIST_NAMES:
        dist = session.scalars(
            select(Distribution).where(Distribution.name == dist_name)
        ).first()
        if dist is None:
            continue

        profiles = session.scalars(
            select(Profile).where(Profile.distribution_id == dist.id)
        ).all()
        profile_names = [p.name for p in profiles]

        package_count = _count_packages_for_dist(session, dist.id)
        group_count = session.scalars(
            select(PackageGroup).where(PackageGroup.distribution_id == dist.id)
        ).all()
        set_count = session.scalars(
            select(PackageSet).where(PackageSet.distribution_id == dist.id)
        ).all()

        summaries.append(RefDistSummary(
            id=dist.id,
            name=dist.name,
            description=dist.description,
            class_name=class_map.get(dist.class_id) if dist.class_id else None,
            default_channel=dist.default_channel,
            profiles=profile_names,
            package_count=package_count,
            group_count=len(group_count),
            set_count=len(set_count),
        ))
    return summaries


def get_reference_distribution(
    session: "Session", name: str
) -> RefDistSummary | None:
    """Return summary for a single reference distribution by name."""
    summaries = list_reference_distributions(session)
    return next((s for s in summaries if s.name == name), None)


def get_reference_distribution_by_id(
    session: "Session", dist_id: str
) -> RefDistSummary | None:
    """Return summary for a single reference distribution by id."""
    summaries = list_reference_distributions(session)
    return next((s for s in summaries if s.id == dist_id), None)


def list_reference_profiles(session: "Session", dist_name: str) -> list[RefDistProfile]:
    """Return detailed profile info for a reference distribution."""
    dist = session.scalars(
        select(Distribution).where(Distribution.name == dist_name)
    ).first()
    if dist is None:
        return []

    board_map = {b.id: b for b in session.scalars(select(Board)).all()}
    arch_map = {a.id: a.name for a in session.scalars(select(Architecture)).all()}
    kernel_map = {k.id: k for k in session.scalars(select(Kernel)).all()}
    tc_map = {t.id: t.name for t in session.scalars(select(Toolchain)).all()}
    pset_map = {ps.id: ps.name for ps in session.scalars(
        select(PackageSet).where(PackageSet.distribution_id == dist.id)
    ).all()}

    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id)
    ).all()

    result: list[RefDistProfile] = []
    for prof in profiles:
        board = board_map.get(prof.board_id) if prof.board_id else None
        kern = kernel_map.get(prof.kernel_id) if prof.kernel_id else None

        packages: list[str] = []
        if prof.package_set_id:
            packages = _packages_for_set(session, prof.package_set_id)

        result.append(RefDistProfile(
            id=prof.id,
            name=prof.name,
            distribution_id=dist.id,
            board_name=board.name if board else None,
            arch_name=arch_map.get(board.arch_id) if board else None,
            kernel_name=f"{kern.name}-{kern.version}" if kern else None,
            toolchain_name=tc_map.get(prof.toolchain_id) if prof.toolchain_id else None,
            package_set_name=pset_map.get(prof.package_set_id) if prof.package_set_id else None,
            packages=packages,
        ))
    return result


def _count_packages_for_dist(session: "Session", dist_id: str) -> int:
    """Count distinct packages reachable from any package set of a distribution."""
    pkg_ids: set[str] = set()
    for pset in session.scalars(
        select(PackageSet).where(PackageSet.distribution_id == dist_id)
    ).all():
        for pid in _package_ids_for_set(session, pset.id):
            pkg_ids.add(pid)
    return len(pkg_ids)


def _package_ids_for_set(session: "Session", set_id: str) -> list[str]:
    pkg_ids: list[str] = []
    for member in session.scalars(
        select(PackageSetMember).where(PackageSetMember.set_id == set_id)
    ).all():
        if member.member_kind == "group" and member.group_id:
            for gm in session.scalars(
                select(PackageGroupMember).where(
                    PackageGroupMember.group_id == member.group_id
                )
            ).all():
                pkg_ids.append(gm.package_id)
        elif member.member_kind == "package" and member.package_id:
            pkg_ids.append(member.package_id)
    return pkg_ids


def _packages_for_set(session: "Session", set_id: str) -> list[str]:
    """Return sorted list of package names reachable from a package set."""
    pkg_ids = _package_ids_for_set(session, set_id)
    if not pkg_ids:
        return []
    pkgs = session.scalars(
        select(Package).where(Package.id.in_(list(set(pkg_ids))))
    ).all()
    return sorted(p.name for p in pkgs)


def validate_reference_distribution(
    session: "Session", dist_name: str
) -> dict[str, object]:
    """Validate that a reference distribution is fully seeded."""
    dist = session.scalars(
        select(Distribution).where(Distribution.name == dist_name)
    ).first()
    if dist is None:
        return {"valid": False, "errors": [f"Distribution '{dist_name}' not found"]}

    errors: list[str] = []

    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id)
    ).all()
    if not profiles:
        errors.append("No profiles defined")
    else:
        for prof in profiles:
            if not prof.package_set_id:
                errors.append(f"Profile '{prof.name}' has no package set")

    groups = session.scalars(
        select(PackageGroup).where(PackageGroup.distribution_id == dist.id)
    ).all()
    if not groups:
        errors.append("No package groups defined")

    pkg_count = _count_packages_for_dist(session, dist.id)
    if pkg_count == 0:
        errors.append("No packages reachable from any package set")

    return {
        "valid": len(errors) == 0,
        "distribution": dist_name,
        "profiles": len(profiles),
        "groups": len(groups),
        "packages": pkg_count,
        "errors": errors,
    }
