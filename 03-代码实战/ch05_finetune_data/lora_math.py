"""第 05 章 · LoRA 参数量与显存估算（面试可手算）

公式：对每个被适配的权重矩阵 W(d_in × d_out)，LoRA 可训练参数 = r × (d_in + d_out)。
Transformer 中 q/v 各一个 d×d 矩阵，则每层 = 4 × r × d；全模型 = 4 × r × d × L。

运行：python ch05_finetune_data/lora_math.py
"""
from __future__ import annotations


def lora_params(r: int, shapes: list[tuple[int, int]]) -> int:
    """shapes: [(d_in, d_out), ...]"""
    if r <= 0:
        raise ValueError("r 必须为正整数")
    return sum(r * (din + dout) for din, dout in shapes)


def estimate_transformer_lora(r: int, d_model: int, n_layers: int, targets: tuple[str, ...] = ("q", "v")) -> int:
    """每个 target 对应一个 d_model × d_model 矩阵。"""
    shapes = [(d_model, d_model)] * (n_layers * len(targets))
    return lora_params(r, shapes)


def memory_gb(params: int, dtype_bytes: int = 2, optimizer_multiplier: float = 4.0, overhead: float = 1.2) -> float:
    """训练显存粗估：权重 + 梯度 + 优化器状态 + 激活/框架开销。"""
    bytes_total = params * dtype_bytes * (1 + optimizer_multiplier) * overhead
    return round(bytes_total / 1024 ** 3, 3)


def main() -> None:
    r, d, layers = 8, 4096, 32
    p_qv = estimate_transformer_lora(r, d, layers, ("q", "v"))
    p_all = estimate_transformer_lora(r, d, layers, ("q", "k", "v", "o"))
    print(f"r={r}, d_model={d}, layers={layers}")
    print(f"仅 q/v       : {p_qv:,} 参数（{p_qv / 1e6:.1f}M），训练显存约 {memory_gb(p_qv)} GB")
    print(f"q/k/v/o 全适配: {p_all:,} 参数（{p_all / 1e6:.1f}M），训练显存约 {memory_gb(p_all)} GB")
    print(f"手算校验：4×{r}×{d}×{layers} = {4 * r * d * layers:,}")


if __name__ == "__main__":
    main()
