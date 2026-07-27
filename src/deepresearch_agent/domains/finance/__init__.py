__all__ = ["FinanceDomainPack", "FinanceGroundedFactRenderer"]


def __getattr__(name: str):
    # Keep low-level vocabulary importable without pulling reporting back into
    # metric coverage during package initialization.
    if name == "FinanceDomainPack":
        from deepresearch_agent.domains.finance.pack import FinanceDomainPack

        return FinanceDomainPack
    if name == "FinanceGroundedFactRenderer":
        from deepresearch_agent.domains.finance.grounded_facts import (
            FinanceGroundedFactRenderer,
        )

        return FinanceGroundedFactRenderer
    raise AttributeError(name)
