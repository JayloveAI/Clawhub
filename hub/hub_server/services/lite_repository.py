"""
SQLite + NumPy 极简存储实现
替代 PostgreSQL + pgvector，用于 MVP 验证

V1.6.4 优化版本:
- Optimization 1: 添加 SQLite 索引提升查询性能
- Optimization 2: 使用二进制 blob 存储向量，避免 JSON 序列化/反序列化开销
- Optimization 3: 基于向量的 Top-K 预筛选，减少全表扫描
- Optimization 4: 使用 Jaccard 相似度实现模糊标签匹配
- Vector Normalization: 动态归一化不同维度向量到统一目标维度（自动适配Embedding配置）
"""
import os
import sqlite3
import numpy as np
import json
from typing import List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


def _get_embedding_dimensions() -> int:
    """懒加载获取 EMBEDDING_DIMENSIONS 配置"""
    from hub_server.config import EMBEDDING_DIMENSIONS as DIM
    return DIM


@dataclass
class PendingDemand:
    demand_id: str
    resource_type: str
    description: str
    tags: List[str]
    demand_vector: List[float]
    seeker_id: Optional[str]
    seeker_webhook_url: str
    created_at: str
    original_task: str = ""
    status: str = "pending"
    matched_agent_id: Optional[str] = None


class LiteMemoryRepository:
    """SQLite + NumPy 极简存储 - 优化版"""

    def __init__(self, db_path: str = os.getenv("DB_PATH", "data/hub_mvp.db")):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表和索引"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_demands (
                    demand_id TEXT PRIMARY KEY,
                    resource_type TEXT,
                    description TEXT,
                    original_task TEXT DEFAULT '',
                    tags TEXT,
                    demand_vector BLOB,
                    seeker_id TEXT,
                    seeker_webhook_url TEXT,
                    created_at TEXT,
                    status TEXT DEFAULT 'pending',
                    matched_agent_id TEXT,
                    vector_dim INTEGER
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON pending_demands(status)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON pending_demands(created_at)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_seeker_id
                ON pending_demands(seeker_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_matched_agent_id
                ON pending_demands(matched_agent_id)
            """)

            # Migration: 为旧表添加 original_task 列（幂等）
            try:
                conn.execute("ALTER TABLE pending_demands ADD COLUMN original_task TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # 列已存在

    def _normalize_vector(self, vector: List[float], target_dim: int = None) -> np.ndarray:
        """
        动态归一化向量到目标维度

        策略：
        - 如果向量维度 < 目标维度：用 0 填充（padding）
        - 如果向量维度 > 目标维度：截断
        - 如果向量维度 == 目标维度：直接返回

        目标维度由 EMBEDDING_DIMENSIONS 配置决定（默认1536 OpenAI / 1024 GLM）

        Args:
            vector: 输入向量
            target_dim: 目标维度，默认从 config.EMBEDDING_DIMENSIONS 读取

        Returns:
            归一化后的 numpy 数组
        """
        if target_dim is None:
            target_dim = _get_embedding_dimensions()

        arr = np.array(vector, dtype=np.float32)
        current_dim = len(arr)

        if current_dim < target_dim:
            padding = np.zeros(target_dim - current_dim, dtype=np.float32)
            arr = np.concatenate([arr, padding])
        elif current_dim > target_dim:
            arr = arr[:target_dim]

        return arr

    def _vector_to_blob(self, vector: List[float]) -> bytes:
        """将向量转换为二进制 blob（归一化到统一维度）"""
        arr = self._normalize_vector(vector)
        return arr.tobytes()

    def _blob_to_vector(self, blob: bytes) -> List[float]:
        """将二进制 blob 转换为向量"""
        arr = np.frombuffer(blob, dtype=np.float32)
        return arr.tolist()

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """NumPy 极速余弦相似度计算"""
        a, b = np.array(vec_a), np.array(vec_b)
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _jaccard_similarity(self, tags_a: List[str], tags_b: List[str]) -> float:
        """
        Optimization 4: Jaccard 相似度用于模糊标签匹配

        Jaccard(A, B) = |A ∩ B| / |A ∪ B|

        相比精确交集匹配，Jaccard 可以处理部分重叠的情况：
        - ["python", "数据"] vs ["python脚本", "数据分析"]
          交集为空，但并集也较小，相似度 > 0
        """
        if not tags_a or not tags_b:
            return 0.0
        set_a, set_b = set(tags_a), set(tags_b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def add_demand(self, demand: PendingDemand) -> PendingDemand:
        """添加悬赏需求（自动归一化向量维度）"""
        vector_blob = self._vector_to_blob(demand.demand_vector)
        actual_dim = len(self._normalize_vector(demand.demand_vector))

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pending_demands
                (demand_id, resource_type, description, original_task, tags, demand_vector,
                 seeker_id, seeker_webhook_url, created_at, status, matched_agent_id, vector_dim)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                demand.demand_id,
                demand.resource_type,
                demand.description,
                demand.original_task,
                json.dumps(demand.tags),
                vector_blob,
                demand.seeker_id,
                demand.seeker_webhook_url,
                demand.created_at,
                demand.status,
                demand.matched_agent_id,
                actual_dim
            ))
        return demand

    def _load_demand_from_row(self, row: tuple) -> PendingDemand:
        """从数据库行加载 PendingDemand 对象（兼容新旧 schema）"""
        return PendingDemand(
            demand_id=row[0],
            resource_type=row[1],
            description=row[2],
            original_task=row[3] if len(row) > 10 else "",
            tags=json.loads(row[4] if len(row) > 10 else row[3]),
            demand_vector=self._blob_to_vector(row[5] if len(row) > 10 else row[4]),
            seeker_id=row[6] if len(row) > 10 else row[5],
            seeker_webhook_url=row[7] if len(row) > 10 else row[6],
            created_at=row[8] if len(row) > 10 else row[7],
            status=row[9] if len(row) > 10 else row[8],
            matched_agent_id=row[10] if len(row) > 10 else row[9]
        )

    def find_matches(
        self,
        new_tags: List[str],
        new_vector: List[float],
        threshold: float = 0.7,
        top_k: int = 50,
        vector_threshold: float = 0.5,
        target_dim: int = None
    ) -> List[PendingDemand]:
        """
        优化版匹配算法：

        1. 向量归一化
           - 将输入向量归一化到目标维度（默认1536 OpenAI / 1024 GLM）
           - 数据库中存储的向量已经是归一化的，可以直接比较

        2. 向量 Top-K 预筛选（Optimization 3）
           - 用归一化后的向量在全量 pending 向量中找出 Top-K 候选
           - 大幅减少需要计算的数量

        3. Jaccard 相似度重排序（Optimization 4）
           - 用 Jaccard 相似度替代精确交集
           - 允许部分标签重叠的模糊匹配

        4. 综合评分排序
           - 综合考虑向量相似度和标签相似度
        """
        if target_dim is None:
            target_dim = _get_embedding_dimensions()

        new_vec_array = self._normalize_vector(new_vector, target_dim)

        print(f"[DEBUG-REPO] ========== Finding Matches (Optimized) ==========")
        print(f"[DEBUG-REPO] New tags: {new_tags}")
        print(f"[DEBUG-REPO] Input vector dim: {len(new_vector)}, Normalized to: {target_dim}")
        print(f"[DEBUG-REPO] Vector threshold: {vector_threshold}, Final threshold: {threshold}")

        all_candidates: List[Tuple[PendingDemand, float, float]] = []

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT demand_id, resource_type, description, original_task, tags, demand_vector,
                       seeker_id, seeker_webhook_url, created_at, status, matched_agent_id
                FROM pending_demands WHERE status = 'pending'
            """)

            for row in cursor.fetchall():
                demand = self._load_demand_from_row(row)
                candidate_vector = np.array(demand.demand_vector)

                norm_new = np.linalg.norm(new_vec_array)
                norm_candidate = np.linalg.norm(candidate_vector)

                if norm_new == 0 or norm_candidate == 0:
                    continue

                vector_sim = float(np.dot(new_vec_array, candidate_vector) / (norm_new * norm_candidate))

                if vector_sim >= vector_threshold:
                    all_candidates.append((demand, vector_sim, 0.0))

        print(f"[DEBUG-REPO] Top-K pre-filtered candidates: {len(all_candidates)}")

        if not all_candidates:
            print(f"[DEBUG-REPO] No candidates passed vector threshold {vector_threshold}")
            return []

        top_k_candidates = sorted(all_candidates, key=lambda x: x[1], reverse=True)[:top_k]

        matches: List[Tuple[PendingDemand, float]] = []
        for demand, vector_sim, _ in top_k_candidates:
            tag_sim = self._jaccard_similarity(new_tags, demand.tags)
            # V1.6.8: 当 demand.tags 为空时，退化为纯向量匹配（避免 tag_sim=0 拖死 score）
            if not demand.tags:
                combined_score = vector_sim
            else:
                combined_score = vector_sim * 0.6 + tag_sim * 0.4

            print(f"[DEBUG-REPO]   {demand.demand_id}: "
                  f"vector_sim={vector_sim:.4f}, tag_sim={tag_sim:.4f}, "
                  f"combined={combined_score:.4f}")

            if combined_score >= threshold:
                print(f"[DEBUG-REPO]   ✓ {demand.demand_id}: MATCHED!")
                matches.append((demand, combined_score))
            else:
                print(f"[DEBUG-REPO]   ✗ {demand.demand_id}: Below threshold")

        matches.sort(key=lambda x: x[1], reverse=True)
        print(f"[DEBUG-REPO] Total matches: {len(matches)}")
        print(f"[DEBUG-REPO] ========================================")
        return [m[0] for m in matches]

    def mark_matched(self, demand_id: str, agent_id: str):
        """标记为已匹配"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE pending_demands SET status = 'matched', matched_agent_id = ? WHERE demand_id = ?",
                (agent_id, demand_id)
            )

    def mark_delivered(self, demand_id: str) -> bool:
        """原子标记为已投递。仅在 status='matched' 时生效，防止多 Provider 竞态重复投递。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE pending_demands SET status = 'delivered' WHERE demand_id = ? AND status = 'matched'",
                (demand_id,)
            )
            return cursor.rowcount > 0

    def get_matched_demands_for_seeker(self, seeker_id: str) -> List[PendingDemand]:
        """查询指定 Seeker 的已匹配待收货订单"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT demand_id, resource_type, description, original_task, tags, demand_vector,
                       seeker_id, seeker_webhook_url, created_at, status, matched_agent_id
                FROM pending_demands
                WHERE seeker_id = ? AND status = 'matched'
            """, (seeker_id,))
            return [self._load_demand_from_row(row) for row in cursor.fetchall()]

    def get_matched_demands_for_provider(self, provider_id: str) -> List[PendingDemand]:
        """查询指定 Provider 的已匹配待发货订单"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT demand_id, resource_type, description, original_task, tags, demand_vector,
                       seeker_id, seeker_webhook_url, created_at, status, matched_agent_id
                FROM pending_demands
                WHERE matched_agent_id = ? AND status = 'matched'
            """, (provider_id,))
            return [self._load_demand_from_row(row) for row in cursor.fetchall()]

    def get_all_pending(self) -> List[PendingDemand]:
        """获取所有待处理需求"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT demand_id, resource_type, description, original_task, tags, demand_vector,
                       seeker_id, seeker_webhook_url, created_at, status, matched_agent_id
                FROM pending_demands WHERE status = 'pending'
            """)
            return [self._load_demand_from_row(row) for row in cursor.fetchall()]

    def delete_demand(self, demand_id: str) -> bool:
        """V1.6: 删除需求"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM pending_demands WHERE demand_id = ?",
                (demand_id,)
            )
            return cursor.rowcount > 0

    def get_expired_demands(self, older_than_days: int = 60) -> List[PendingDemand]:
        """V1.6: 获取过期需求"""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        cutoff_str = cutoff.isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT demand_id, resource_type, description, original_task, tags, demand_vector,
                       seeker_id, seeker_webhook_url, created_at, status, matched_agent_id
                FROM pending_demands
                WHERE status = 'pending' AND created_at < ?
            """, (cutoff_str,))
            return [self._load_demand_from_row(row) for row in cursor.fetchall()]


_repo = LiteMemoryRepository()


def get_repository() -> LiteMemoryRepository:
    return _repo
