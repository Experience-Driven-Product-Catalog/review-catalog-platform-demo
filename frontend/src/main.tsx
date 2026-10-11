import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  ArrowUpRight,
  ArrowRight,
  Monitor,
  MessageSquare,
  FileText,
  Plus,
  ShieldCheck,
  Check,
  LoaderCircle,
  RotateCcw,
  ChevronDown,
  Download,
} from "lucide-react";
import {
  catalog,
  stream,
  type Catalog,
  type Condition,
  type Session,
  type ChatResult,
  type ReportResult,
} from "./api";
import "./styles.css";

type Message = {
  role: "user" | "assistant";
  text: string;
  conditions?: Condition[];
};
const examples = [
  "27인치 QHD 모니터 중 30만 원 이하로 찾아줘",
  "빛샘이 적다는 리뷰가 있는 모니터를 비교해줘",
  "문서 작업에 사용할 모니터를 함께 골라줘",
];
const money = (n: number) => n.toLocaleString("ko-KR");
function Markdown({ text }: { text: string }) {
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
function Conditions({ items }: { items: Condition[] }) {
  return (
    items.length > 0 && (
      <div className="conditions" aria-label="적용 조건">
        {items.map((c, i) => (
          <span
            key={i}
            className={"condition " + (c.type === "체감" ? "experience" : "")}
          >
            <b>{c.type}</b>
            {c.condition}: {c.value}
          </span>
        ))}
      </div>
    )
  );
}
function App() {
  const [page, setPage] = useState(location.hash.slice(1) || "home"),
    [data, setData] = useState<Catalog | null>(null),
    [loadError, setLoadError] = useState("");
  const [messages, setMessages] = useState<Message[]>([]),
    [session, setSession] = useState<Session | null>(null),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(""),
    [error, setError] = useState(""),
    [resetOpen, setResetOpen] = useState(false);
  const [product, setProduct] = useState(""),
    [review, setReview] = useState(""),
    [report, setReport] = useState<ReportResult | null>(null),
    [reportBusy, setReportBusy] = useState(false),
    [reportStatus, setReportStatus] = useState(""),
    [reportError, setReportError] = useState("");
  const controller = useRef<AbortController | null>(null),
    reportController = useRef<AbortController | null>(null),
    epoch = useRef(0),
    bottom = useRef<HTMLDivElement>(null),
    textarea = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const fn = () => setPage(location.hash.slice(1) || "home");
    window.addEventListener("hashchange", fn);
    catalog()
      .then((d) => {
        setData(d);
        setProduct(d.products[0]?.product_id || "");
      })
      .catch(() =>
        setLoadError(
          "카탈로그에 연결하지 못했습니다. 잠시 후 새로고침해 주세요.",
        ),
      );
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  useEffect(() => {
    if (!messages.length && !input && !review && !report) return;
    const fn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", fn);
    return () => window.removeEventListener("beforeunload", fn);
  }, [messages.length, input, review, report]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, status]);
  function reset() {
    epoch.current++;
    controller.current?.abort();
    setMessages([]);
    setSession(null);
    setError("");
    setInput("");
    setBusy(false);
    setStatus("");
    setResetOpen(false);
    textarea.current?.focus();
  }
  async function send(text = input) {
    if (!text.trim() || busy) return;
    const current = epoch.current;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: text.trim() }]);
    setStatus("요청을 시작하고 있습니다.");
    try {
      const result = await stream<ChatResult>(
        "/chat",
        { message: text.trim(), ...(session || {}) },
        abort.signal,
        (s) => {
          if (current === epoch.current) setStatus(s);
        },
      );
      if (current !== epoch.current) return;
      setSession({
        previous_response_id: result.previous_response_id,
        continuation: result.continuation,
        applied_filters: result.applied_filters,
        applied_conditions: result.applied_conditions,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: result.answer,
          conditions: result.applied_conditions,
        },
      ]);
    } catch (e) {
      if (
        current === epoch.current &&
        !(e instanceof DOMException && e.name === "AbortError")
      ) {
        setError(e instanceof Error ? e.message : "연결 오류가 발생했습니다.");
        setInput(text);
      }
    } finally {
      if (current === epoch.current) {
        setBusy(false);
        setStatus("");
      }
    }
  }
  async function submitReport(e: React.FormEvent) {
    e.preventDefault();
    if (reportBusy) return;
    const abort = new AbortController();
    reportController.current = abort;
    setReportBusy(true);
    setReportError("");
    setReport(null);
    setReportStatus("보고서를 준비하고 있습니다.");
    try {
      setReport(
        await stream<ReportResult>(
          "/report",
          { product_id: product, review },
          abort.signal,
          setReportStatus,
        ),
      );
    } catch (e) {
      setReportError(e instanceof Error ? e.message : "보고서 생성 오류");
    } finally {
      setReportBusy(false);
    }
  }
  function download() {
    if (!report) return;
    const blob = new Blob([report.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = report.product.model + "-보고서.md";
    a.click();
    URL.revokeObjectURL(url);
  }
  const navigate = (p: string) => {
    location.hash = p;
  };
  return (
    <>
      <header className="site-header">
        <a href="#home" className="brand">
          <span className="brand-icon">
            <Monitor size={19} />
          </span>
          Review Catalog<span className="brand-tag">DEMO</span>
        </a>
        <nav aria-label="주 메뉴">
          {[
            ["home", "프로젝트"],
            ["chat", "쇼핑 Agent"],
            ["report", "리뷰 보고서"],
          ].map(([id, label]) => (
            <a
              key={id}
              href={"#" + id}
              aria-current={page === id ? "page" : undefined}
              className={page === id ? "active" : ""}
            >
              {label}
            </a>
          ))}
        </nav>
        <a
          className="github"
          href="https://github.com/Experience-Driven-Product-Catalog/review-catalog-platform-demo"
          target="_blank"
          rel="noreferrer"
        >
          GitHub <ArrowUpRight size={15} />
        </a>
      </header>
      {loadError && <div className="global-notice error">{loadError}</div>}
      {data && !data.api_ready && (
        <div className="global-notice">
          <span className="dot amber" />
          API 연결 준비 중 · 카탈로그를 살펴볼 수 있으며, 채팅과 보고서 생성은
          API 키 등록 후 이용할 수 있습니다.
        </div>
      )}
      {page === "home" && (
        <main className="home">
          <div className="hero-grid">
            <section>
              <div className="eyebrow">
                <span className="dot" /> EXPERIENCE-DRIVEN PRODUCT CATALOG
              </div>
              <h1>
                스펙 너머의 경험까지,
                <br />
                <span>함께 고르는 모니터.</span>
              </h1>
              <p className="hero-copy">
                크기와 해상도부터 빛샘, 눈의 편안함까지.
                <br />
                객관적인 사양과 실제 리뷰를 한 대화에서 비교해 보세요.
              </p>
              <div className="hero-actions">
                <a href="#chat" className="primary">
                  채팅 페이지로 이동 <ArrowUpRight size={18} />
                </a>
                <a href="#report" className="secondary">
                  내 리뷰 분석하기 <ArrowRight size={17} />
                </a>
              </div>
              <div className="trust">
                <ShieldCheck size={16} />
                등록된 9개 상품과 확인 가능한 리뷰 근거만 사용합니다.
              </div>
            </section>
            <div className="preview-card">
              <div className="preview-title">
                <span className="brand-icon small">
                  <Monitor size={15} />
                </span>
                사양에 경험을 더하면
                <span className="tiny-label">HOW IT WORKS</span>
              </div>
              <div className="mini-question">
                “27인치 모니터, 빛샘도 살펴보고 싶어요.”
              </div>
              <div className="preview-steps">
                <div>
                  <span className="step-icon">01</span>
                  <div>
                    <b>객관 조건 확인</b>
                    <p>화면 크기 · 해상도 · 고정 가격</p>
                  </div>
                  <Check size={16} />
                </div>
                <div>
                  <span className="step-icon teal">02</span>
                  <div>
                    <b>체감 리뷰 탐색</b>
                    <p>원래 속성 · 상태 · 상반된 경험</p>
                  </div>
                  <Check size={16} />
                </div>
                <div>
                  <span className="step-icon">03</span>
                  <div>
                    <b>근거와 함께 비교</b>
                    <p>일치 리뷰 수와 원문을 확인</p>
                  </div>
                  <Check size={16} />
                </div>
              </div>
              <p className="preview-note">
                조건에 맞는 상품이 없으면, 없다고 알려드립니다.
              </p>
            </div>
          </div>
          <section className="stats-strip">
            <div>
              <strong>
                9<span>개</span>
              </strong>
              <p>비교 대상 모니터</p>
            </div>
            <div>
              <strong>
                {data ? money(data.metadata.counts.reviews) : "—"}
                <span>개</span>
              </strong>
              <p>고정 카탈로그 리뷰</p>
            </div>
            <div>
              <strong>
                {data ? money(data.metadata.counts.opinion_units) : "—"}
                <span>개</span>
              </strong>
              <p>추출된 사용 경험</p>
            </div>
            <div className="stat-description">
              <p>
                많은 상품을 나열하기보다,
                <br />
                <b>선택의 근거를 분명하게.</b>
              </p>
            </div>
          </section>
          <section className="explore">
            <div className="section-heading">
              <div>
                <div className="eyebrow">TWO WAYS TO EXPLORE</div>
                <h2>경험을 이해하는 두 가지 방법</h2>
              </div>
              <span>입력한 내용은 카탈로그에 저장되지 않습니다.</span>
            </div>
            <div className="feature-grid">
              <a href="#chat" className="feature-card">
                <MessageSquare />
                <h3>대화하며 조건 좁히기</h3>
                <p>
                  원하는 사양과 사용 경험을 말해 보세요.
                  <br />
                  적용된 조건을 확인하며 비교할 수 있습니다.
                </p>
                <span>
                  쇼핑 Agent 시작 <ArrowUpRight size={17} />
                </span>
              </a>
              <a href="#report" className="feature-card">
                <FileText />
                <h3>내 리뷰를 기존 경험과 비교하기</h3>
                <p>
                  리뷰에서 속성과 감성을 추출하고,
                  <br />
                  상품의 기존 리뷰 요약을 함께 확인합니다.
                </p>
                <span>
                  보고서 만들기 <ArrowUpRight size={17} />
                </span>
              </a>
            </div>
          </section>
          <section className="scope-note">
            <b>공개 포트폴리오 데모</b>
            <p>
              고정된 9개 모니터만 다룹니다. 가격과 판매 상태는 과거 자료이며,
              리뷰 근거는 제품의 성능이나 만족도를 보장하지 않습니다.
            </p>
          </section>
        </main>
      )}
      {page === "chat" && (
        <main className="chat-layout">
          <aside className="chat-sidebar">
            <div className="eyebrow">SHOPPING AGENT</div>
            <h2>
              나에게 맞는
              <br />
              조건부터.
            </h2>
            <button
              className="new-chat"
              onClick={() => (messages.length ? setResetOpen(true) : reset())}
            >
              <Plus size={16} />새 대화
            </button>
            <div className="sidebar-block">
              <span className="tiny-label">현재 적용 조건</span>
              {session?.applied_conditions.length ? (
                <Conditions items={session.applied_conditions} />
              ) : (
                <p>
                  원하는 조건을 말하면
                  <br />
                  이곳에 정리해 드립니다.
                </p>
              )}
            </div>
            <div className="sidebar-bottom">
              <ShieldCheck size={18} />
              <b>한 번에 하나의 대화</b>
              <p>
                새 대화를 시작하면 화면의 기존 내용이 지워집니다. 페이지를 닫거나
                새로고침하면 화면에서 복구할 수 없습니다. 서버 보안 기록은 삭제되지 않습니다.
              </p>
              <p>
                제출한 대화와 답변은 보안 점검을 위해 비공개 저장소에 보관되며
                90일 후 자동 삭제 대상이 됩니다. 개인정보나 비밀번호를 입력하지 마세요.
              </p>
              <details>
                <summary>
                  대화 처리 안내 <ChevronDown size={13} />
                </summary>
                <p>
                  보안 기록은 운영자만 조회하며 카탈로그에 반영하지 않습니다. 이전 문맥 연결에는
                  OpenAI의 응답 저장과 응답 ID를 사용합니다. 새 대화에서는 이전
                  ID와 조건을 전송하지 않습니다.
                </p>
              </details>
            </div>
          </aside>
          <section className="chat-main">
            <div className="chat-topbar">
              <span>
                <span className="dot" />
                모니터 쇼핑 Agent
              </span>
              <span>9개 상품 · 근거 기반 비교</span>
            </div>
            <div className="conversation" aria-live="polite">
              {messages.length === 0 ? (
                <div className="chat-empty">
                  <div className="empty-icon">
                    <Monitor size={29} />
                  </div>
                  <div className="eyebrow">LET’S FIND YOUR MONITOR</div>
                  <h1>어떤 모니터를 찾고 있나요?</h1>
                  <p>
                    필요한 사양이나 사용하면서 중요하게 느끼는 점을 알려주세요.
                  </p>
                  <div className="suggestions">
                    {examples.map((t) => (
                      <button
                        key={t}
                        onClick={() => {
                          setInput(t);
                          textarea.current?.focus();
                        }}
                      >
                        {t}
                        <ArrowUpRight size={16} />
                      </button>
                    ))}
                  </div>
                  <p className="small-muted">
                    예시 질문은 실제 검색 전에는 조건으로 적용되지 않습니다.
                  </p>
                </div>
              ) : (
                messages.map((m, i) => (
                  <article key={i} className={"message " + m.role}>
                    <div className="message-author">
                      {m.role === "user" ? "나" : "REVIEW CATALOG"}
                    </div>
                    {m.conditions && <Conditions items={m.conditions} />}
                    <Markdown text={m.text} />
                  </article>
                ))
              )}
              {busy && (
                <div className="working" role="status">
                  <LoaderCircle size={16} className="spin" />
                  {status}
                </div>
              )}
              {error && (
                <div className="inline-error" role="alert">
                  {error}
                </div>
              )}
              <div ref={bottom} />
            </div>
            <div className="composer-wrap">
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
              >
                <label className="sr-only" htmlFor="chat-input">
                  모니터 검색 질문
                </label>
                <textarea
                  ref={textarea}
                  id="chat-input"
                  rows={2}
                  maxLength={4000}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder="예: 27인치 QHD, 눈이 편하다는 리뷰가 있는 모니터"
                />
                <button
                  type="submit"
                  className="send"
                  disabled={busy || !input.trim()}
                  aria-label="질문 보내기"
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={20} />
                  ) : (
                    <ArrowUp size={20} />
                  )}
                </button>
              </form>
              <p>
                대화는 이 페이지에서만 유지됩니다. 조건을 임의로 완화하지
                않으며, 근거가 부족하면 알려드립니다.
              </p>
            </div>
          </section>
        </main>
      )}
      {page === "report" && (
        <main className="report-page">
          <section className="report-heading">
            <div className="eyebrow">REVIEW → EVIDENCE</div>
            <h1>
              내 경험을,
              <br />
              다른 리뷰와 나란히.
            </h1>
            <p>
              속성 추출부터 기존 리뷰 비교, 상품 요약까지
              <br />
              하나의 보고서에서 확인하세요.
            </p>
            <div className="report-policy">
              <ShieldCheck size={19} />
              <p>
                입력 리뷰와 생성 보고서는 보안 점검을 위해 비공개 저장소에 보관하며 90일 후 자동 삭제 대상이 됩니다. 개인정보나 비밀번호를 입력하지 마세요.
                <br />
                기존 표현과 정확히 일치한 의견만 비교합니다.
              </p>
            </div>
            <a className="text-link" href="#chat">
              채팅 페이지로 이동 <ArrowUpRight size={16} />
            </a>
          </section>
          <div className="report-content">
            <form className="report-form" onSubmit={submitReport}>
              <div className="form-heading">
                <FileText size={20} />
                <h2>리뷰 보고서 만들기</h2>
                <span>01 — INPUT</span>
              </div>
              <label htmlFor="product">사용한 상품</label>
              <select
                id="product"
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                disabled={reportBusy}
              >
                {data?.products.map((p) => (
                  <option key={p.product_id} value={p.product_id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <label htmlFor="review">
                나의 사용 경험 <span>최대 8,000자</span>
              </label>
              <textarea
                id="review"
                rows={7}
                value={review}
                onChange={(e) => setReview(e.target.value)}
                maxLength={8000}
                minLength={3}
                required
                disabled={reportBusy}
                placeholder="직접 사용하며 느낀 점을 자유롭게 적어 주세요. 예: 화면이 선명해서 문서를 읽기 편하지만, 빛샘이 조금 거슬립니다."
              />
              <div className="form-footer">
                <span>{review.length.toLocaleString()} / 8,000</span>
                <button
                  className="primary"
                  disabled={reportBusy || !product || review.trim().length < 3}
                >
                  {reportBusy ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <FileText size={17} />
                  )}
                  보고서 생성
                </button>
              </div>
              {reportBusy && (
                <div className="working" role="status">
                  {reportStatus}
                </div>
              )}
              {reportError && (
                <div className="inline-error" role="alert">
                  {reportError}
                </div>
              )}
            </form>
            {report ? (
              <section className="report-result">
                <div className="result-toolbar">
                  <span>
                    <Check size={16} />
                    보고서 생성 완료
                  </span>
                  <button className="secondary" onClick={download}>
                    <Download size={15} />
                    Markdown 저장
                  </button>
                </div>
                <Markdown text={report.markdown} />
              </section>
            ) : (
              <div className="report-explainer">
                <div>
                  <span>01</span>
                  <b>의견 추출</b>
                  <p>속성·상태·감성·원문</p>
                </div>
                <ArrowRight size={16} />
                <div>
                  <span>02</span>
                  <b>정확 일치 비교</b>
                  <p>일치·상충·판단 불가</p>
                </div>
                <ArrowRight size={16} />
                <div>
                  <span>03</span>
                  <b>통합 보고서</b>
                  <p>상품 요약과 대안 근거</p>
                </div>
              </div>
            )}
          </div>
        </main>
      )}
      {!["home", "chat", "report"].includes(page) && (
        <main className="home">
          <h1>페이지를 찾을 수 없습니다.</h1>
          <button onClick={() => navigate("home")} className="primary">
            홈으로 이동
          </button>
        </main>
      )}
      {page !== "chat" && (
        <footer>
          <span>Review Catalog</span>
          <p>객관적인 사양과 주관적인 경험 사이에서.</p>
          <span>PORTFOLIO DEMO · 2026</span>
        </footer>
      )}
      {resetOpen && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-title"
          >
            <RotateCcw size={25} />
            <h2 id="reset-title">새 대화를 시작할까요?</h2>
            <p>
              화면의 대화 내용과 적용 조건이 지워져 복구할 수 없습니다.
              서버 보안 기록은 삭제되지 않으며 90일 보관 정책을 따릅니다.
            </p>
            <div>
              <button className="secondary" onClick={() => setResetOpen(false)}>
                취소
              </button>
              <button className="primary" onClick={reset} autoFocus>
                지우고 시작
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
