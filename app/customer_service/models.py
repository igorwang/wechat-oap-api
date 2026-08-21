"""微信客服的持久化模型."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# 生产用 PostgreSQL 的 JSONB（可索引）；测试跑 SQLite 时退回普通 JSON。
JSONType = JSON().with_variant(JSONB(), "postgresql")


class WeChatFollower(Base):
    """公众号关注者——客服门禁的判据来源.

    以 openid 为主键而不是 unionid：取关回调只带 openid，且 user/info 在
    subscribe=0 时不再返回 unionid，所以必须能仅凭 openid 定位到这条记录。
    unionid 用来和客服侧的客户对账，建索引。

    取关时不删行、只把 subscribed 置 false——保留 openid→unionid 的对应关系，
    否则重新关注时又得重新调接口去换。
    """

    __tablename__ = "wechat_followers"

    openid: Mapped[str] = mapped_column(String(128), primary_key=True)
    unionid: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    subscribed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    subscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeChatCustomer(Base):
    """微信客服的客户（微信用户）.

    external_userid 是微信客服体系内的客户标识，仅在客户 48 小时内有过互动时
    才可用于查询接口——所以信息必须在会话发生的当下落库。

    unionid 需要企业在管理后台绑定同主体的公众号/小程序（且该号已绑定微信开放
    平台）才会下发，未绑定时为 NULL。
    """

    __tablename__ = "wechat_customers"

    external_userid: Mapped[str] = mapped_column(String(128), primary_key=True)
    unionid: Mapped[str | None] = mapped_column(String(128), index=True, default=None)
    nickname: Mapped[str | None] = mapped_column(String(255), default=None)
    avatar: Mapped[str | None] = mapped_column(String(512), default=None)
    gender: Mapped[int | None] = mapped_column(Integer, default=None)

    # 最近一次会话的上下文
    open_kfid: Mapped[str | None] = mapped_column(String(128), default=None)
    scene: Mapped[str | None] = mapped_column(String(128), default=None)
    scene_param: Mapped[str | None] = mapped_column(String(255), default=None)

    message_count: Mapped[int] = mapped_column(BigInteger, default=0)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 保留接口原始返回，日后新增字段可回溯补齐
    raw: Mapped[dict | None] = mapped_column(JSONType, default=None)
