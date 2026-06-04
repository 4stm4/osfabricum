"""Boot Chain service layer (M31)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from osfabricum.db.models import (
    BootChain,
    BootChainBinding,
    BootChainFile,
    BootChainTemplate,
    BootScheme,
)
from osfabricum.db.session import sync_session as get_session


def create_boot_chain(
    name: str,
    boot_scheme_id: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new boot chain."""
    with get_session(db_url) as session:
        # Verify boot scheme exists
        scheme = session.get(BootScheme, boot_scheme_id)
        if not scheme:
            raise ValueError(f"Boot scheme {boot_scheme_id!r} not found")
        
        boot_chain = BootChain(
            id=str(uuid4()),
            name=name,
            boot_scheme_id=boot_scheme_id,
            description=description,
            metadata_json=metadata,
        )
        session.add(boot_chain)
        session.commit()
        return _boot_chain_to_dict(boot_chain)


def list_boot_chains(*, db_url: str | None = None) -> list[dict[str, Any]]:
    """List all boot chains."""
    with get_session(db_url) as session:
        stmt = select(BootChain).order_by(BootChain.name)
        chains = session.execute(stmt).scalars().all()
        return [_boot_chain_to_dict(c) for c in chains]


def get_boot_chain(boot_chain_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Get boot chain with all templates and files."""
    with get_session(db_url) as session:
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        # Get templates
        templates_stmt = select(BootChainTemplate).where(
            BootChainTemplate.boot_chain_id == boot_chain_id
        )
        templates = session.execute(templates_stmt).scalars().all()
        
        # Get files
        files_stmt = select(BootChainFile).where(
            BootChainFile.boot_chain_id == boot_chain_id
        )
        files = session.execute(files_stmt).scalars().all()
        
        # Get bindings
        bindings_stmt = select(BootChainBinding).where(
            BootChainBinding.boot_chain_id == boot_chain_id
        )
        bindings = session.execute(bindings_stmt).scalars().all()
        
        result = _boot_chain_to_dict(chain)
        result["templates"] = [_boot_chain_template_to_dict(t) for t in templates]
        result["files"] = [_boot_chain_file_to_dict(f) for f in files]
        result["bindings"] = [_boot_chain_binding_to_dict(b) for b in bindings]
        
        return result


def add_boot_chain_template(
    boot_chain_id: str,
    template_type: str,
    content: str,
    variables: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a template to a boot chain."""
    with get_session(db_url) as session:
        # Verify boot chain exists
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        template = BootChainTemplate(
            id=str(uuid4()),
            boot_chain_id=boot_chain_id,
            template_type=template_type,
            content=content,
            variables=variables,
            metadata_json=metadata,
        )
        session.add(template)
        session.commit()
        return _boot_chain_template_to_dict(template)


def add_boot_chain_file(
    boot_chain_id: str,
    filename: str,
    placement: str,
    content_template: str | None = None,
    template_id: str | None = None,
    required: bool = True,
    permissions: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a file to a boot chain."""
    with get_session(db_url) as session:
        # Verify boot chain exists
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        # Verify template if specified
        if template_id:
            template = session.get(BootChainTemplate, template_id)
            if not template:
                raise ValueError(f"Template {template_id!r} not found")
        
        file = BootChainFile(
            id=str(uuid4()),
            boot_chain_id=boot_chain_id,
            filename=filename,
            content_template=content_template,
            template_id=template_id,
            placement=placement,
            required=required,
            permissions=permissions,
            metadata_json=metadata,
        )
        session.add(file)
        session.commit()
        return _boot_chain_file_to_dict(file)


def bind_boot_chain(
    boot_chain_id: str,
    board_id: str | None = None,
    profile_id: str | None = None,
    is_default: bool = False,
    priority: int = 100,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Bind a boot chain to a board and/or profile."""
    with get_session(db_url) as session:
        # Verify boot chain exists
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        binding = BootChainBinding(
            id=str(uuid4()),
            boot_chain_id=boot_chain_id,
            board_id=board_id,
            profile_id=profile_id,
            is_default=is_default,
            priority=priority,
            metadata_json=metadata,
        )
        session.add(binding)
        session.commit()
        return _boot_chain_binding_to_dict(binding)


def list_boot_chain_bindings(
    board_id: str | None = None,
    profile_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """List boot chain bindings, optionally filtered by board/profile."""
    with get_session(db_url) as session:
        stmt = select(BootChainBinding)
        
        if board_id:
            stmt = stmt.where(BootChainBinding.board_id == board_id)
        if profile_id:
            stmt = stmt.where(BootChainBinding.profile_id == profile_id)
        
        stmt = stmt.order_by(BootChainBinding.priority.desc())
        bindings = session.execute(stmt).scalars().all()
        return [_boot_chain_binding_to_dict(b) for b in bindings]


def render_boot_chain(
    boot_chain_id: str,
    variables: dict[str, Any],
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Render boot chain files with provided variables."""
    with get_session(db_url) as session:
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        # Get all files
        files_stmt = select(BootChainFile).where(
            BootChainFile.boot_chain_id == boot_chain_id
        )
        files = session.execute(files_stmt).scalars().all()
        
        rendered_files = []
        for file in files:
            content = file.content_template or ""
            
            # If file references a template, get template content
            if file.template_id:
                template = session.get(BootChainTemplate, file.template_id)
                if template:
                    content = template.content
            
            # Simple variable substitution (in production, use Jinja2)
            for key, value in variables.items():
                content = content.replace(f"{{{key}}}", str(value))
            
            rendered_files.append({
                "filename": file.filename,
                "placement": file.placement,
                "content": content,
                "permissions": file.permissions,
                "required": file.required,
            })
        
        return {
            "boot_chain_id": boot_chain_id,
            "boot_chain_name": chain.name,
            "files": rendered_files,
        }


def validate_boot_chain(
    boot_chain_id: str,
    context: dict[str, Any],
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Validate that boot chain has all required components."""
    with get_session(db_url) as session:
        chain = session.get(BootChain, boot_chain_id)
        if not chain:
            raise ValueError(f"Boot chain {boot_chain_id!r} not found")
        
        # Get required files
        files_stmt = select(BootChainFile).where(
            BootChainFile.boot_chain_id == boot_chain_id,
            BootChainFile.required == True,  # noqa: E712
        )
        required_files = session.execute(files_stmt).scalars().all()
        
        errors = []
        warnings = []
        
        # Check if kernel is referenced
        has_kernel = any("kernel" in f.filename.lower() for f in required_files)
        if not has_kernel and "kernel" not in context:
            errors.append("No kernel file or kernel context provided")
        
        # Check if initramfs is needed but missing
        scheme = session.get(BootScheme, chain.boot_scheme_id)
        if scheme and "initramfs" in scheme.name.lower():
            has_initramfs = any("initramfs" in f.filename.lower() for f in required_files)
            if not has_initramfs and "initramfs" not in context:
                warnings.append("Initramfs may be required but not found")
        
        # Check for DTB if needed
        if context.get("board_requires_dtb"):
            has_dtb = any("dtb" in f.filename.lower() or "dt" in f.filename.lower() for f in required_files)
            if not has_dtb:
                errors.append("Board requires device tree but none found in boot chain")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "required_files_count": len(required_files),
        }


# Helper functions to convert ORM objects to dicts

def _boot_chain_to_dict(chain: BootChain) -> dict[str, Any]:
    return {
        "id": chain.id,
        "name": chain.name,
        "boot_scheme_id": chain.boot_scheme_id,
        "description": chain.description,
        "metadata": chain.metadata_json,
        "created_at": chain.created_at.isoformat() if chain.created_at else None,
    }


def _boot_chain_template_to_dict(template: BootChainTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "boot_chain_id": template.boot_chain_id,
        "template_type": template.template_type,
        "content": template.content,
        "variables": template.variables,
        "metadata": template.metadata_json,
    }


def _boot_chain_file_to_dict(file: BootChainFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "boot_chain_id": file.boot_chain_id,
        "filename": file.filename,
        "content_template": file.content_template,
        "template_id": file.template_id,
        "placement": file.placement,
        "required": file.required,
        "permissions": file.permissions,
        "metadata": file.metadata_json,
    }


def _boot_chain_binding_to_dict(binding: BootChainBinding) -> dict[str, Any]:
    return {
        "id": binding.id,
        "boot_chain_id": binding.boot_chain_id,
        "board_id": binding.board_id,
        "profile_id": binding.profile_id,
        "is_default": binding.is_default,
        "priority": binding.priority,
        "metadata": binding.metadata_json,
    }

# Made with Bob
