(function () {
  "use strict";

  var nav = document.querySelector(".nav");
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function closeMenu() {
    if (!nav || !toggle) return;
    nav.classList.remove("menu-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "打开导航");
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
    });
    if (links) {
      links.addEventListener("click", function (event) {
        if (event.target.closest("a")) closeMenu();
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu();
    });
  }

  var path = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  document.querySelectorAll(".nav-links a").forEach(function (link) {
    var href = (link.getAttribute("href") || "").split("#")[0].toLowerCase();
    if (href && href === path) link.classList.add("active");
    if ((path === "" || path === "/") && href === "index.html") link.classList.add("active");
  });

  function startCarousel(root, slideSelector, interval) {
    var slides = Array.prototype.slice.call(root.querySelectorAll(slideSelector));
    if (slides.length < 2) return;
    var dots = root.querySelectorAll(".prof-dots span, .g-dots span");
    var index = 0;
    var paused = false;
    function show(next) {
      slides.forEach(function (slide, slideIndex) {
        slide.classList.toggle("active", slideIndex === next);
      });
      dots.forEach(function (dot, dotIndex) {
        dot.classList.toggle("on", dotIndex === next);
      });
    }
    show(0);
    if (reduceMotion) return;
    root.addEventListener("mouseenter", function () { paused = true; });
    root.addEventListener("mouseleave", function () { paused = false; });
    root.addEventListener("focusin", function () { paused = true; });
    root.addEventListener("focusout", function () { paused = false; });
    window.setInterval(function () {
      if (paused || document.hidden) return;
      index = (index + 1) % slides.length;
      show(index);
    }, interval);
  }

  document.querySelectorAll(".prof-card").forEach(function (card) {
    startCarousel(card, ".slide", 4200);
  });
  document.querySelectorAll(".gallery").forEach(function (gallery) {
    startCarousel(gallery, ".g-slide", 4800);
  });
})();
