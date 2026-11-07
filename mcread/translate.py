"""Turn amulet's universal blocks into Java blockstates.

The resource pack is indexed by Java blockstate, so every block read out of a
Bedrock save has to pass through here before a model can be looked up.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import PyMCTranslate
from amulet.api.block import Block
from amulet.api.block_entity import BlockEntity

JAVA = "java"
BEDROCK = "bedrock"
UNIVERSAL = "universal"


@dataclass(frozen=True)
class TranslationResult:
    """What came back from `from_universal`, including the failure modes."""

    block: Optional[Block]
    block_entity: Optional[BlockEntity]
    extra_needed: bool
    """True when the real output depends on neighbouring blocks."""
    became_entity: bool
    """True when the block translated into an entity instead of a block."""
    passed_through: bool
    """True when the block came back still in the universal namespace.

    `from_universal` does not raise on an unknown block. It logs a warning and
    returns the input unchanged, which would then silently miss in the resource
    pack, so the namespace is the only reliable signal."""
    error: Optional[str]

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.block is not None
            and not self.passed_through
        )


@lru_cache(maxsize=1)
def translation_manager() -> PyMCTranslate.TranslationManager:
    return PyMCTranslate.new_translation_manager()


def newest_version(platform: str) -> tuple[int, ...]:
    return max(translation_manager().version_numbers(platform))


@lru_cache(maxsize=1)
def universal_version():
    return translation_manager().get_version(UNIVERSAL, (1, 0, 0))


def specification_for(version, block: Block) -> Optional[dict]:
    """A version's declared property schema for a block, or None if unknown."""
    try:
        return version.block.get_specification(block.namespace, block.base_name)
    except Exception:
        return None


class JavaTranslator:
    """Translate universal blocks to one pinned Java version."""

    def __init__(self, version: tuple[int, ...] | None = None) -> None:
        self.version_number = version or newest_version(JAVA)
        self._version = translation_manager().get_version(JAVA, self.version_number)

    @property
    def version(self):
        return self._version

    def translate(self, block: Block) -> TranslationResult:
        try:
            output, block_entity, extra_needed = self._version.block.from_universal(
                block
            )
        except Exception as exc:  # PyMCTranslate raises a variety of types
            return TranslationResult(
                block=None,
                block_entity=None,
                extra_needed=False,
                became_entity=False,
                passed_through=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not isinstance(output, Block):
            return TranslationResult(
                block=None,
                block_entity=None,
                extra_needed=bool(extra_needed),
                became_entity=True,
                passed_through=False,
                error=None,
            )

        passed_through = output.namespace.startswith(UNIVERSAL)
        return TranslationResult(
            block=output,
            block_entity=block_entity,
            extra_needed=bool(extra_needed),
            became_entity=False,
            passed_through=passed_through,
            error=(
                f"no translation known for {output.namespaced_name}"
                if passed_through
                else None
            ),
        )

    def specification(self, block: Block) -> Optional[dict]:
        """The version's declared property schema for a block, if it knows one."""
        try:
            return self._version.block.get_specification(
                block.namespace, block.base_name
            )
        except Exception:
            return None
