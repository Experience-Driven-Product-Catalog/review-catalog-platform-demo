import type { SVGProps } from "react";
type Props = SVGProps<SVGSVGElement> & { size?: number };
const icon = (path: string) => ({ size = 20, children, ...props }: Props) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="square" strokeLinejoin="miter" aria-hidden={props["aria-label"] ? undefined : true} {...props}><path d={path} />{children}</svg>
);
export const ArrowUp = icon("M12 20V4m-7 7 7-7 7 7");
export const ArrowUpRight = icon("M5 19 19 5M5 5h14v14");
export const ArrowRight = icon("M3 12h18m-7-7 7 7-7 7");
export const Monitor = icon("M3 4h18v13H3zM12 17v4m-5 0h10M7 8h4m-4 4h10");
export const MessageSquare = icon("M3 4h18v13H9l-6 4V4Z");
export const FileText = icon("M5 2h9l5 5v15H5zM14 2v6h5M9 12h6m-6 5h6");
export const Plus = icon("M12 4v16M4 12h16");
export const ShieldCheck = icon("M4 3h16v18H4zM8 11l3 3 5-6");
export const Check = icon("m4 12 5 5L20 6");
export const LoaderCircle = icon("M12 3a9 9 0 1 1-9 9");
export const RotateCcw = icon("M4 4v6h6M4 10a8 8 0 1 1 1 8");
export const ChevronDown = icon("m5 9 7 7 7-7");
export const Download = icon("M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4");
export const Search = icon("M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-1 5 6 6");
export const ListFilter = icon("M3 5h18M6 12h12m-9 7h6");
export const ArrowDownUp = icon("M7 3v18m-4-4 4 4 4-4M17 21V3m-4 4 4-4 4 4");
