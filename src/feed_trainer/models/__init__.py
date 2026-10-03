from .base import Answer, DecisionModel, ModelResult


def load_model(name: str) -> DecisionModel:
    """name：laya（預設 multilingual）、laya-<checkpoint>、jev、jev-<版本>。"""
    if name == "laya":
        from .laya import LayaModel

        return LayaModel()
    if name.startswith("laya-"):
        from .laya import LayaModel

        return LayaModel(checkpoint=name.removeprefix("laya-"))
    if name == "jev":
        from .jev import JevModel

        return JevModel()
    if name.startswith("jev-"):
        from .jev import JevModel

        return JevModel(model=name)
    raise ValueError(f"未知模型：{name}")


__all__ = ["Answer", "DecisionModel", "ModelResult", "load_model"]
