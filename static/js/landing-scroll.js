/* ============================================================
   Landing page scroll timeline  reproduces the Lumio video motion grammar.
   Depends on Lenis, GSAP, ScrollTrigger, SplitType  all self-hosted in static/vendor/.
   Loaded from memoria/templates/memoria/landing.html only.
   ============================================================ */

(function () {
  "use strict";

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("landing-scroll-ready");

    if (prefersReducedMotion) {
      return;
    }

    if (!window.gsap || !window.ScrollTrigger || !window.Lenis || !window.SplitType) {
      console.warn("[landing-scroll] one or more libraries failed to load");
      return;
    }

    const { gsap, ScrollTrigger, Lenis, SplitType } = window;

    gsap.registerPlugin(ScrollTrigger);

    // ----------------------------------------------------------------
    // E15  Smooth inertial scroll via Lenis hooked into GSAP ticker.
    // ----------------------------------------------------------------
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      wheelMultiplier: 1.0,
    });

    lenis.on("scroll", ScrollTrigger.update);

    gsap.ticker.add((time) => {
      lenis.raf(time * 1000);
    });
    gsap.ticker.lagSmoothing(0);

    window.landingLenis = lenis;

    // ----------------------------------------------------------------
    // Helper  split each .reveal-split heading into characters so they
    // can be animated individually without touching the source text.
    // ----------------------------------------------------------------
    const splitEls = document.querySelectorAll(".reveal-split");
    const splits = [];
    splitEls.forEach((el) => {
      const split = new SplitType(el, { types: "words,chars", tagName: "span" });
      splits.push(split);
    });

    // ----------------------------------------------------------------
    // E1 + E6  Hero intro  char stagger on heading, staged reveal of
    // subtitle and CTA for a polished first paint.
    // ----------------------------------------------------------------
    const heroSection = document.querySelector("#hero");
    const heroHeading = document.querySelector("#hero-heading");
    if (heroHeading) {
      const chars = heroHeading.querySelectorAll(".char");
      const heroTimeline = gsap.timeline({ defaults: { ease: "power3.out" } });
      heroTimeline.from(chars, {
        opacity: 0,
        y: 16,
        filter: "blur(12px)",
        duration: 0.95,
        stagger: 0.022,
      }, 0.1);
      const heroParagraph = heroSection?.querySelector("p");
      if (heroParagraph) {
        heroTimeline.from(heroParagraph, {
          opacity: 0,
          y: 18,
          duration: 0.7,
        }, "-=0.35");
      }
      const heroCta = heroSection?.querySelector(".landing-cta-group");
      if (heroCta) {
        heroTimeline.from(heroCta, {
          opacity: 0,
          y: 20,
          scale: 0.96,
          duration: 0.65,
        }, "-=0.45");
      }
    }

    // Subtle "breathing" scale on the hero background orbs (covered by CSS keyframes).
    // Add a gentle y-parallax on the hero heading as user scrolls the hero section.
    if (heroHeading && heroSection) {
      gsap.to(heroHeading, {
        y: -40,
        opacity: 0.55,
        ease: "none",
        scrollTrigger: {
          trigger: heroSection,
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });
    }

    // ----------------------------------------------------------------
    // E4  Vertical beam parallax drives the layer faster than content.
    // ----------------------------------------------------------------
    const beam = document.querySelector(".beam-layer");
    if (beam) {
      gsap.to(beam, {
        yPercent: -18,
        ease: "none",
        scrollTrigger: {
          trigger: document.body,
          start: "top top",
          end: "bottom bottom",
          scrub: true,
        },
      });
    }

    // ----------------------------------------------------------------
    // E6  Every other .reveal-split heading fades in when scrolled into view.
    // Skips the hero heading since it has its own timeline above.
    // ----------------------------------------------------------------
    splits.forEach((split) => {
      const el = split.elements[0];
      if (!el || el.id === "hero-heading") return;
      const chars = el.querySelectorAll(".char");
      gsap.from(chars, {
        opacity: 0,
        y: 10,
        filter: "blur(10px)",
        duration: 0.7,
        ease: "power2.out",
        stagger: 0.018,
        scrollTrigger: {
          trigger: el,
          start: "top 82%",
          toggleActions: "play reverse play reverse",
        },
      });
    });

    // ----------------------------------------------------------------
    // E8  Underline sweep bar under each h2.
    // ----------------------------------------------------------------
    document.querySelectorAll(".underline-sweep").forEach((el) => {
      gsap.to(el, {
        scaleX: 1,
        duration: 0.8,
        ease: "power2.out",
        scrollTrigger: {
          trigger: el,
          start: "top 85%",
          toggleActions: "play reverse play reverse",
        },
      });
    });

    // ----------------------------------------------------------------
    // E10  Feature cards cascade up into view.
    // ----------------------------------------------------------------
    const featureGrid = document.querySelector("#feature-cards");
    if (featureGrid) {
      gsap.to(featureGrid.querySelectorAll(".feature-card"), {
        opacity: 1,
        y: 0,
        scale: 1,
        duration: 0.9,
        ease: "power2.out",
        stagger: 0.14,
        scrollTrigger: {
          trigger: featureGrid,
          start: "top 75%",
          toggleActions: "play reverse play reverse",
        },
      });
    }

    // ----------------------------------------------------------------
    // E3 repurposed  Chat bubbles inside bubble-ticker containers.
    // ----------------------------------------------------------------
    document.querySelectorAll(".bubble-ticker").forEach((container) => {
      const parentSection = container.closest("section");
      if (!parentSection) return;
      gsap.to(container.children, {
        opacity: 1,
        y: 0,
        duration: 0.5,
        ease: "power2.out",
        stagger: 0.08,
        scrollTrigger: {
          trigger: parentSection,
          start: "top 70%",
          end: "bottom 30%",
          scrub: 0.6,
        },
      });
    });

    // ----------------------------------------------------------------
    // Problem stats  staggered reveal and counter tick on enter.
    // ----------------------------------------------------------------
    const statRows = document.querySelectorAll(".stat-row");
    if (statRows.length) {
      gsap.from(statRows, {
        opacity: 0,
        y: 30,
        duration: 0.6,
        ease: "power2.out",
        stagger: 0.18,
        scrollTrigger: {
          trigger: "#problem-stats",
          start: "top 78%",
          toggleActions: "play reverse play reverse",
        },
      });

      statRows.forEach((row) => {
        const target = row.querySelector(".stat-number");
        if (!target) return;
        const finalValue = parseFloat(target.dataset.value || target.textContent) || 0;
        const suffix = target.dataset.suffix || "%";
        const counter = { val: 0 };
        gsap.to(counter, {
          val: finalValue,
          duration: 1.6,
          ease: "power2.out",
          scrollTrigger: {
            trigger: row,
            start: "top 85%",
            toggleActions: "restart none restart none",
          },
          onUpdate: () => {
            target.textContent = Math.round(counter.val) + suffix;
          },
        });
      });
    }

    // Problem cards, compare cards, and step cards cascade per-section.
    const cardSections = new Map();
    document.querySelectorAll(".problem-card, .compare-card, .step-card").forEach((card) => {
      const section = card.closest("section");
      if (!section) return;
      if (!cardSections.has(section)) cardSections.set(section, []);
      cardSections.get(section).push(card);
    });
    cardSections.forEach((cards, section) => {
      gsap.from(cards, {
        opacity: 0,
        y: 34,
        scale: 0.96,
        duration: 0.7,
        ease: "power2.out",
        stagger: 0.12,
        scrollTrigger: {
          trigger: section,
          start: "top 78%",
          toggleActions: "play reverse play reverse",
        },
      });
    });

    // Agent-demo chat bubble reveal tied to its containing section.
    // Adds the .is-playing class to kick off the CSS keyframe demo.
    document.querySelectorAll(".agent-demo").forEach((demo) => {
      gsap.from(demo, {
        opacity: 0,
        y: 28,
        duration: 0.8,
        ease: "power2.out",
        scrollTrigger: {
          trigger: demo,
          start: "top 85%",
          toggleActions: "play reverse play reverse",
          onEnter: () => {
            demo.classList.remove("is-playing");
            void demo.offsetWidth;
            demo.classList.add("is-playing");
          },
          onEnterBack: () => {
            demo.classList.remove("is-playing");
            void demo.offsetWidth;
            demo.classList.add("is-playing");
          },
          onLeave: () => demo.classList.remove("is-playing"),
          onLeaveBack: () => demo.classList.remove("is-playing"),
        },
      });
    });

    // ----------------------------------------------------------------
    // S1  Nav background morphs once the user scrolls past the hero top.
    // ----------------------------------------------------------------
    const nav = document.querySelector(".landing-nav");
    if (nav) {
      ScrollTrigger.create({
        start: "top -60",
        end: 99999,
        toggleClass: { className: "nav-scrolled", targets: ".landing-nav" },
      });
    }

    // ----------------------------------------------------------------
    // E13 + E14  Integrations orbit  tiles circle slowly around the
    // center. The orbit stage (which is scaled to an oval) rotates,
    // and each tile counter-rotates so logos stay upright. The center
    // logo pulses via CSS but never spins (we counter-rotate it here).
    // ----------------------------------------------------------------
    const orbitStage = document.querySelector("#orbit-stage");
    if (orbitStage) {
      const stageRing = document.createElement("div");
      stageRing.className = "orbit-ring-wrap";
      Array.from(orbitStage.querySelectorAll(".orbit-ring")).forEach((r) => stageRing.appendChild(r));
      orbitStage.appendChild(stageRing);

      gsap.to(stageRing, {
        rotate: 360,
        duration: 32,
        ease: "none",
        repeat: -1,
      });

      orbitStage.querySelectorAll(".orbit-tile").forEach((tile) => {
        gsap.to(tile, {
          rotate: -360,
          duration: 32,
          ease: "none",
          repeat: -1,
        });
      });

      const swapSequence = ["messaging", "productivity", "calendar", "code", "mail"];
      swapSequence.forEach((category, index) => {
        ScrollTrigger.create({
          trigger: "#integrations-orbit",
          start: `top+=${index * 20}% center`,
          end: `top+=${(index + 1) * 20}% center`,
          onToggle: (self) => {
            document.querySelectorAll(".category-rail li").forEach((li) => {
              li.classList.toggle(
                "is-active",
                li.dataset.category === category && self.isActive,
              );
            });
          },
        });
      });
    }

    // ----------------------------------------------------------------
    // Refresh after fonts and images settle so triggers recompute layout.
    // ----------------------------------------------------------------
    window.addEventListener("load", () => ScrollTrigger.refresh());
  });
})();
