/** Language picker: 中文 / English, remembers choice in localStorage */
(function () {
  const LANG_KEY = "officelego-lang";
  const pageLang = document.documentElement.lang.startsWith("en") ? "en" : "zh";

  function siteBase() {
    let p = location.pathname;
    if (p.endsWith("index-en.html")) return p.slice(0, -"index-en.html".length);
    if (p.endsWith("index.html")) return p.slice(0, -"index.html".length);
    if (!p.endsWith("/")) p += "/";
    return p;
  }

  function targetFor(lang) {
    return siteBase() + (lang === "en" ? "index-en.html" : "index.html");
  }

  function saveLang(lang) {
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch (_) {}
  }

  const params = new URLSearchParams(location.search);
  const qLang = params.get("lang");
  if (qLang === "en" || qLang === "zh") {
    saveLang(qLang);
    const want = qLang;
    if (want !== pageLang) {
      location.replace(targetFor(want) + location.hash);
      return;
    }
  } else {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "en" && pageLang === "zh") {
      location.replace(targetFor("en") + location.hash);
      return;
    }
    if (saved === "zh" && pageLang === "en") {
      location.replace(targetFor("zh") + location.hash);
      return;
    }
  }

  document.querySelectorAll(".lang-picker [data-lang]").forEach((btn) => {
    const lang = btn.getAttribute("data-lang");
    if (lang === pageLang) btn.classList.add("active");
    else btn.classList.remove("active");
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (lang === pageLang) return;
      saveLang(lang);
      location.href = targetFor(lang) + location.hash;
    });
  });
})();
