"""체감 검색의 입력·출력 계약. 검증 규칙은 이 모듈에 모은다."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Sentiment = Literal["positive", "negative", "mixed", "neutral", "unknown"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttributeClause(InputModel):
    aspect_cluster_id: str = Field(min_length=1, description="속성 군집 ID")
    raw_aspect_ids: list[str] | None = Field(default=None, min_length=1, description="원래 속성 ID 목록. 생략하면 군집 전체")


class AttributeSelector(InputModel):
    clauses: list[AttributeClause] = Field(min_length=1, description="OR로 결합할 속성 선택 절")


class ExperienceCondition(InputModel):
    condition_id: str = Field(min_length=1, description="호출 안에서 유일한 조건 ID")
    attribute: AttributeSelector
    desired_state_ids: list[str] | None = Field(default=None, min_length=1, description="원하는 원래 상태 ID. 생략하면 상태 제한 없음")
    contrary_state_ids: list[str] = Field(default_factory=list, description="명시적으로 지정한 상반 상태 ID")
    sentiments: list[Sentiment] | None = Field(default=None, min_length=1, description="일치 상태의 리뷰별 감성 제한")
    min_matching_reviews: int = Field(default=1, ge=1, description="최소 일치 리뷰 수")
    max_contrary_reviews: int | None = Field(default=None, ge=0, description="상반 리뷰 수 상한. 기본은 제한 없음")

    @model_validator(mode="after")
    def check_contrary_limit(self):
        if self.max_contrary_reviews is not None and not self.contrary_state_ids:
            raise ValueError("상반 리뷰 상한에는 contrary_state_ids가 필요합니다.")
        if set(self.desired_state_ids or []) & set(self.contrary_state_ids):
            raise ValueError("원하는 상태와 상반 상태 ID가 겹칩니다.")
        return self


class ExperienceSort(InputModel):
    attribute: AttributeSelector
    metric: Literal["positive_wilson_lower", "state_wilson_lower"] = "positive_wilson_lower"
    desired_state_ids: list[str] | None = Field(default=None, min_length=1, description="상태 점수에 사용할 원래 상태 ID")
    order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def check_states(self):
        if self.metric == "state_wilson_lower" and not self.desired_state_ids:
            raise ValueError("state_wilson_lower에는 desired_state_ids가 필요합니다.")
        if self.metric == "positive_wilson_lower" and self.desired_state_ids is not None:
            raise ValueError("긍정 점수는 속성 전체로 계산합니다. 상태 제한은 state_wilson_lower를 사용하세요.")
        return self


class EvidenceTopic(InputModel):
    topic_id: str = Field(min_length=1)
    attribute: AttributeSelector
    desired_state_ids: list[str] | None = Field(default=None, min_length=1)
    contrary_state_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_overlap(self):
        if set(self.desired_state_ids or []) & set(self.contrary_state_ids):
            raise ValueError("원하는 상태와 상반 상태 ID가 겹칩니다.")
        return self


class EvidenceRequest(InputModel):
    attribute: AttributeSelector
    products: list[str] | None = Field(default=None, min_length=1)
    desired_state_ids: list[str] | None = Field(default=None, min_length=1)
    contrary_state_ids: list[str] = Field(default_factory=list)
    group: Literal["all", "matching", "contrary", "other", "unknown_state"] = "all"
    sentiments: list[Sentiment] | None = Field(default=None, min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    include_full_review: bool = False

    @model_validator(mode="after")
    def check_groups(self):
        if self.group == "contrary" and not self.contrary_state_ids:
            raise ValueError("상반 근거 조회에는 contrary_state_ids가 필요합니다.")
        if set(self.desired_state_ids or []) & set(self.contrary_state_ids):
            raise ValueError("원하는 상태와 상반 상태 ID가 겹칩니다.")
        return self


class PageRequest(InputModel):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AppliedCondition(BaseModel):
    """화면은 type으로 색상을 정하고 condition:value로 표시한다."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["객관", "체감", "판매"]
    condition: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ResultModel(BaseModel):
    """기존 객관 결과의 필드를 보존하는 확장 출력 모델."""
    model_config = ConfigDict(extra="allow")
    applied_conditions: list[AppliedCondition] = Field(default_factory=list, description="화면용 적용 조건. type별 색상으로 condition:value를 표시")


class AttributeSearchResult(ResultModel):
    attributes: list[dict[str, Any]]
    total_count: int
    next_offset: int | None
    data_version: str


class StateListResult(ResultModel):
    states: list[dict[str, Any]]
    total_count: int
    next_offset: int | None
    data_version: str


class ReviewEvidenceResult(ResultModel):
    reviews: list[dict[str, Any]]
    total_count: int
    next_offset: int | None
    data_version: str


class ProductSearchResult(ResultModel):
    applied_filters_markdown: str
    applied_filters: dict[str, Any]
    total_products: int
    matched_count: int
    products: list[dict[str, Any]]
    table_markdown: str
