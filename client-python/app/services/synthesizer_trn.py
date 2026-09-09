"""RVC 模型架构模块（来自 RVC-Project，v2 使用 SynthesizerTrnMs256NSFsid）。

这里把 infer.module 里的 v2 架构以 SynthesizerTrn 的名字暴露给 rvc_service 使用。
"""

from infer.module.models import SynthesizerTrnMs768NSFsid as SynthesizerTrn

__all__ = ["SynthesizerTrn"]
