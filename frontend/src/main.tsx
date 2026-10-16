import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  ArrowUpRight,
  ArrowRight,
  Monitor,
  FileText,
  Plus,
  ShieldCheck,
  Check,
  LoaderCircle,
  RotateCcw,
  ChevronDown,
  Download,
  Search,
  ListFilter,
  ArrowDownUp,
} from "./icons";
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
  "30만 원 이하에 무료배송인 판매처가 있는 모니터를 찾아줘",
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
  const visible = items.filter(c => ["객관", "체감", "판매"].includes(c.type) && !/^제한\s*없음$/.test(c.value.trim()));
  return visible.length > 0 && (
    <div className="conditions" aria-label="적용 조건">
      {visible.map((c, i) => {
        const method = c.method || "filter";
        const Icon = method === "search" ? Search : method === "sort" ? ArrowDownUp : ListFilter;
        const label = method === "search" ? "검색" : method === "sort" ? "정렬" : "필터링";
        return <span key={i} className={"condition " + (c.type === "체감" ? "experience" : "")}>
          <Icon size={12} aria-label={label} role="img"><title>{label}</title></Icon>
          <b>{c.type}:</b><span>{c.value}</span>
        </span>;
      })}
    </div>
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
    [resetOpen, setResetOpen] = useState(false),
    [noticeAccepted, setNoticeAccepted] = useState(false);
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
    textarea = useRef<HTMLTextAreaElement>(null),
    notice = useRef<HTMLDialogElement>(null),
    resetDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (resetOpen) resetDialog.current?.showModal(); }, [resetOpen]);
  useEffect(() => {
    if (page === "chat" && !noticeAccepted) notice.current?.showModal();
    else if (page === "chat" && noticeAccepted) textarea.current?.focus();
  }, [page, noticeAccepted]);
  useEffect(() => {
    const fn = () => setPage(location.hash.slice(1) || "home");
    window.addEventListener("hashchange", fn);
    catalog()
      .then((d) => {
        setData(d);
        setProduct(d.products[0] ? String(d.products[0].product_id) : "");
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
    bottom.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "end" });
  }, [messages, status]);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("revealed");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    document.querySelectorAll("[data-reveal]").forEach(element => {
      element.classList.add("reveal-ready");
      observer.observe(element);
    });
    return () => observer.disconnect();
  }, [page]);
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
    if (!text.trim() || busy || !noticeAccepted) return;
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
      <a className="skip-link" href="#main-content" onClick={e => { e.preventDefault(); document.getElementById("main-content")?.focus(); }}>본문으로 이동</a>
      <header className="site-header">
        <a href="#home" className="brand">
          <span className="brand-icon">
            <Monitor size={19} />
          </span>
          <span className="brand-name">Review Catalog<small>경험 기반 제품 카탈로그</small></span><span className="brand-tag">DEMO</span>
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
      {loadError && <div role="alert" className="global-notice error">{loadError}</div>}
      {data && !data.api_ready && (
        <div className="global-notice">
          <span className="dot amber" />
          API 연결 준비 중 · 카탈로그를 살펴볼 수 있으며, 채팅과 보고서 생성은
          API 키 등록 후 이용할 수 있습니다.
        </div>
      )}
      {page === "home" && (
        <main id="main-content" tabIndex={-1} className="home">
          <div className="edition-line"><span>EXPERIENCE-DRIVEN PRODUCT CATALOG</span><span>모니터 편 / 01</span></div>
          <div className="hero-grid">
            <section className="hero-intro">
              <div className="eyebrow">사양을 읽고, 경험을 비교하다</div>
              <h1>좋은 모니터의 기준,<br /><span>당신의 경험에서.</span></h1>
              <p className="hero-copy">크기와 해상도로 좁히고, 빛샘과 눈의 편안함까지 살펴보세요. 아홉 개 모니터의 사양과 실제 리뷰에서 선택의 근거를 찾습니다.</p>
              <div className="hero-actions">
                <a href="#chat" className="primary">모니터 비교 시작 <ArrowRight size={18} /></a>
                <a href="#report" className="text-link">내 리뷰 분석하기 <ArrowUpRight size={16} /></a>
              </div>
              <p className="trust">조건에 맞는 상품이 없으면, 없다고 알려드립니다.</p>
            </section>
            <figure className="catalog-figure" aria-label="모니터의 사양과 사용 경험을 함께 살펴보는 개념도">
              <div className="figure-index"><span>관찰 노트</span><span>FIG. 01</span></div>
              <svg className="monitor-drawing" viewBox="0 0 480 270" aria-hidden="true">
                <path className="drawing-guide" d="M30 40h420M30 218h420M66 15v225M410 15v225" />
                <rect className="drawing-body" x="77" y="53" width="325" height="181" rx="3" />
                <rect className="drawing-screen" x="88" y="64" width="303" height="157" />
                <path className="drawing-grid" d="M88 116h303M88 169h303M189 64v157M290 64v157" />
                <path className="drawing-diagonal" d="m97 211 285-138m-285 0 285 138" />
                <path className="drawing-stand" d="M223 234v20l-37 9h107l-36-9v-20" />
                <path className="drawing-guide" d="M77 33h325m-325-5v10m325-10v10" />
                <circle cx="240" cy="228" r="2" fill="currentColor" />
              </svg>
              <figcaption>
                <div><span className="note-number">01 / 사양</span><b>숫자로 확인하는 것</b><p>화면 크기 · 해상도 · 주사율</p></div>
                <div><span className="note-number">02 / 경험</span><b>써 본 사람에게 묻는 것</b><p>빛샘 · 가독성 · 눈의 편안함</p></div>
              </figcaption>
              <p className="figure-footnote">사양은 조건으로, 리뷰는 판단의 근거로.</p>
            </figure>
          </div>
          <section className="stats-strip" data-reveal>
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
          <section className="explore" data-reveal>
            <div className="section-heading"><div><div className="eyebrow">사용 안내</div><h2>고르기 전에도, 써 본 뒤에도.</h2></div><span>입력 내용은 고정 카탈로그에 반영하지 않습니다.</span></div>
            <div className="feature-grid">
              <a href="#chat" className="feature-card"><span className="feature-number">01</span><div><h3>다음 모니터를 고를 때</h3><p>원하는 사양과 사용 경험을 말하고,<br />적용된 조건에 따라 상품을 비교하세요.</p><span className="feature-action">쇼핑 Agent 열기 <ArrowUpRight size={16} /></span></div></a>
              <a href="#report" className="feature-card"><span className="feature-number">02</span><div><h3>내 경험이 궁금할 때</h3><p>직접 쓴 리뷰를 기존 리뷰와 나란히 놓고,<br />같은 경험과 다른 평가를 확인하세요.</p><span className="feature-action">리뷰 보고서 만들기 <ArrowUpRight size={16} /></span></div></a>
            </div>
          </section>
          <section className="scope-note" data-reveal>
            <b>공개 포트폴리오 데모</b>
            <p>
              고정된 9개 모니터만 다룹니다. 판매처·가격·배송·재고·링크는 데모 가상 정보이며,
              리뷰 근거는 제품의 성능이나 만족도를 보장하지 않습니다.
            </p>
          </section>
        </main>
      )}
      {page === "chat" && (
        <main id="main-content" tabIndex={-1} className="chat-layout">
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
                <p className="mobile-policy">새 대화를 시작하면 화면의 기존 내용이 지워지며, 페이지를 닫거나 새로고침하면 복구할 수 없습니다. 제출한 대화와 답변은 보안 점검을 위해 비공개 저장소에 보관하고 90일 후 자동 삭제 대상이 됩니다. 새 대화는 서버 기록을 삭제하지 않습니다. 개인정보나 비밀번호를 입력하지 마세요.</p>
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
              <span>MONITORS / 09</span>
            </div>
            <div className="conversation" aria-live="polite">
              {messages.length === 0 ? (
                <div className="chat-empty">
                  <div className="eyebrow">01 / 모니터 탐색</div>
                  <h1>어떤 경험을 찾고 있나요?</h1>
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
                        <span className="suggestion-type">{["사양", "경험", "판매"][examples.indexOf(t)]}</span><span>{t}</span>
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
                화면의 대화는 이 페이지에서만 유지됩니다. 조건을 임의로 완화하지
                않으며, 근거가 부족하면 알려드립니다.
              </p>
            </div>
          </section>
        </main>
      )}
      {page === "report" && (
        <main id="main-content" tabIndex={-1} className="report-page">
          <section className="report-heading">
            <div className="eyebrow">02 / 리뷰 보고서</div>
            <h1>
              내 경험을,
              <br />
              리뷰와 나란히.
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
                <span>REVIEW NOTE</span>
              </div>
              <label htmlFor="product">사용한 상품</label>
              <select
                id="product"
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                disabled={reportBusy || !data}
                required
              >
                {!data && <option value="">{loadError ? "카탈로그 연결을 확인해 주세요" : "상품을 불러오는 중…"}</option>}
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
              <p className="field-hint">경험을 3자 이상 입력해 주세요. 구체적인 장점과 아쉬운 점이 비교에 도움이 됩니다.</p>
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
        <main id="main-content" tabIndex={-1} className="home">
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
      {page === "chat" && !noticeAccepted && (
        <dialog ref={notice} className="modal demo-notice" aria-labelledby="notice-title" onCancel={e => e.preventDefault()}>
          <ShieldCheck size={25} />
          <h2 id="notice-title">시작 전에 확인해 주세요</h2>
          <p>본 데모는 AI HUB의 <a href="https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&aihubDataSe=data&dataSetSn=71603" target="_blank" rel="noopener noreferrer">속성 기반 감성 분석 데이터셋</a>에서 추출한 9개의 모니터 상품을 기반으로 수행됩니다. 이에 따라 가격, 배송 정보와 같은 판매 속성은 과거 데이터 혹은 더미 데이터로 구성되어 있습니다.</p>
          <div><button className="primary" onClick={() => setNoticeAccepted(true)} autoFocus>확인하고 시작</button></div>
        </dialog>
      )}
      {resetOpen && (
          <dialog ref={resetDialog} className="modal" aria-labelledby="reset-title" onCancel={() => setResetOpen(false)}>
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
          </dialog>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
