/* Markdown 格式化渲染，无外部依赖。
 * renderMarkdown(text) 返回可直接写入 innerHTML 的 HTML 字符串。
 * 先转义原文再放行受控标签，可对未完成的流式文本反复调用。
 */
const MD_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const MD_STYLE_ID = "md-format-style";
const MD_CSS = [
  ".md-body{line-height:1.75;word-break:break-word}",
  ".md-body h1,.md-body h2,.md-body h3,.md-body h4{margin:14px 0 8px;line-height:1.35;font-weight:700}",
  ".md-body h1{font-size:1.35em}.md-body h2{font-size:1.2em}.md-body h3{font-size:1.08em}.md-body h4{font-size:1em}",
  ".md-body p{margin:8px 0}",
  ".md-body ul,.md-body ol{margin:8px 0;padding-left:22px}",
  ".md-body li{margin:3px 0}",
  ".md-body code{background:rgba(127,127,127,.16);border-radius:4px;padding:1px 5px;font-size:.92em}",
  ".md-body pre.md-code{background:rgba(127,127,127,.14);border-radius:8px;padding:10px 12px;overflow:auto;margin:10px 0}",
  ".md-body pre.md-code code{background:none;padding:0;white-space:pre}",
  ".md-body blockquote{margin:10px 0;padding:2px 12px;border-left:3px solid rgba(127,127,127,.5);opacity:.92}",
  ".md-body .md-table-wrap{overflow:auto;margin:10px 0}",
  ".md-body table{border-collapse:collapse;width:100%;font-size:.95em}",
  ".md-body th,.md-body td{border:1px solid rgba(127,127,127,.35);padding:6px 9px;text-align:left;vertical-align:top}",
  ".md-body th{background:rgba(127,127,127,.14);font-weight:600}",
  ".md-body hr{border:none;border-top:1px solid rgba(127,127,127,.35);margin:14px 0}",
  ".md-body a{text-decoration:underline}",
].join("");

function mdEscape(value) {
  return String(value).replace(/[&<>"']/g, (character) => MD_ESCAPES[character]);
}

function mdInline(text) {
  const codes = [];
  let out = String(text).replace(/`([^`]+)`/g, (match, code) => {
    codes.push(code);
    return "\u0001" + (codes.length - 1) + "\u0001";
  });
  out = mdEscape(out);
  out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return out.replace(/\u0001(\d+)\u0001/g, (match, index) => "<code>" + mdEscape(codes[Number(index)]) + "</code>");
}

function mdIsTableRow(line) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function mdIsTableRule(line) {
  return /^\s*\|[\s:|-]+\|\s*$/.test(line) && line.indexOf("-") !== -1;
}

function mdSplitRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function mdRender(source) {
  const lines = String(source == null ? "" : source).replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*```/.test(line)) {
      const info = line.replace(/^\s*```/, "").trim();
      const buffer = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buffer.push(lines[i]); i += 1; }
      i += 1;
      out.push('<pre class="md-code"><code' + (info ? ' data-lang="' + mdEscape(info) + '"' : "") + ">" + mdEscape(buffer.join("\n")) + "</code></pre>");
      continue;
    }

    if (/^\s*$/.test(line)) { i += 1; continue; }

    const heading = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      out.push("<h" + level + ">" + mdInline(heading[2].trim()) + "</h" + level + ">");
      i += 1;
      continue;
    }

    if (/^\s{0,3}([-*_])\s*(\1\s*){2,}$/.test(line)) { out.push("<hr>"); i += 1; continue; }

    if (mdIsTableRow(line) && i + 1 < lines.length && mdIsTableRule(lines[i + 1])) {
      const head = mdSplitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && mdIsTableRow(lines[i])) { rows.push(mdSplitRow(lines[i])); i += 1; }
      const table = ['<div class="md-table-wrap"><table><thead><tr>'];
      head.forEach((cell) => table.push("<th>" + mdInline(cell) + "</th>"));
      table.push("</tr></thead><tbody>");
      rows.forEach((row) => {
        table.push("<tr>");
        head.forEach((cell, index) => table.push("<td>" + mdInline(row[index] || "") + "</td>"));
        table.push("</tr>");
      });
      table.push("</tbody></table></div>");
      out.push(table.join(""));
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
      out.push("<blockquote>" + mdRender(quote.join("\n")) + "</blockquote>");
      continue;
    }

    const bullet = /^\s{0,3}[-*+]\s+/;
    const ordered = /^\s{0,3}\d+[.)]\s+/;
    if (bullet.test(line) || ordered.test(line)) {
      const tag = ordered.test(line) ? "ol" : "ul";
      const items = [];
      while (i < lines.length && (bullet.test(lines[i]) || ordered.test(lines[i]))) {
        items.push(lines[i].replace(/^\s{0,3}([-*+]|\d+[.)])\s+/, ""));
        i += 1;
      }
      out.push("<" + tag + ">" + items.map((item) => "<li>" + mdInline(item) + "</li>").join("") + "</" + tag + ">");
      continue;
    }

    const paragraph = [];
    while (
      i < lines.length &&
      !/^\s*$/.test(lines[i]) &&
      !/^\s*```/.test(lines[i]) &&
      !/^\s{0,3}#{1,6}\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i]) &&
      !bullet.test(lines[i]) &&
      !ordered.test(lines[i]) &&
      !mdIsTableRow(lines[i])
    ) { paragraph.push(lines[i]); i += 1; }

    if (paragraph.length) out.push("<p>" + paragraph.map(mdInline).join("<br>") + "</p>");
    else i += 1;
  }
  return out.join("\n");
}

function renderMarkdown(source) {
  if (typeof document !== "undefined" && !document.getElementById(MD_STYLE_ID)) {
    const style = document.createElement("style");
    style.id = MD_STYLE_ID;
    style.textContent = MD_CSS;
    document.head.appendChild(style);
  }
  try {
    return '<div class="md-body">' + mdRender(source) + "</div>";
  } catch (error) {
    return '<div class="md-body"><p>' + mdEscape(source) + "</p></div>";
  }
}
