/**
 * Snowflake background animation
 *
 * Derived from "Snowflake Generator" by Ivan Rudnicki
 * https://openprocessing.org/sketch/1406642
 * Licensed under CC BY-NC-SA 3.0
 * https://creativecommons.org/licenses/by-nc-sa/3.0
 *
 * Changes: ported from p5.js to vanilla canvas API; removed interactivity
 * and sound; adapted for use as a static background with auto-morphing and
 * continuous rotation.
 *
 * This file is licensed under CC BY-NC-SA 3.0 (not the MIT license that
 * covers the rest of the RIME codebase).
 */

(function () {
  const canvas = document.getElementById("rime-snowflake-bg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  function lerp(a, b, t) { return a + (b - a) * t; }

  // ── Piece: one crystal element at a given (x,y) relative to snowflake center ──
  class Piece {
    constructor(x, y, r1, r2, alpha, br, stroke) {
      this.x = x; this.y = y;
      this.r1 = 0; this.r2 = 0;
      this.tr1 = r1; this.tr2 = r2;
      this.alpha = 0; this.ta = alpha;
      this.br = br;
      this.stroke = stroke; // true = outlined, false = filled
    }

    shift() {
      this.r1    = lerp(this.r1,    this.tr1, 0.05);
      this.r2    = lerp(this.r2,    this.tr2, 0.05);
      this.alpha = lerp(this.alpha, this.ta,  0.08);
    }

    draw(step) {
      const r1 = this.r1 * step;
      const r2 = this.r2 * step;
      const a  = this.alpha / 255;

      ctx.save();
      ctx.translate(this.x * step, this.y * step);
      ctx.rotate(7 * Math.PI / 6);

      const pts = 6;
      const ang = Math.PI * 2 / pts;

      ctx.beginPath();
      for (let i = 0; i < pts; i++) {
        const a1 = i * ang;
        ctx.lineTo(Math.cos(a1) * r2, Math.sin(a1) * r2);
        ctx.lineTo(Math.cos(a1 + ang / 2) * r1, Math.sin(a1 + ang / 2) * r1);
      }
      ctx.closePath();

      if (this.stroke) {
        ctx.fillStyle   = `rgba(192,246,251,${a * 0.25})`;
        ctx.strokeStyle = `rgba(192,246,251,${Math.max(0, 0.7 - a) * 0.9})`;
        ctx.lineWidth   = 1;
        ctx.fill();
        ctx.stroke();
      } else {
        ctx.fillStyle = `rgba(192,246,251,${a * 0.35})`;
        ctx.fill();
      }

      ctx.restore();
    }
  }

  // ── Snowflake: 5 rings × 6 pieces + centre piece ──────────────────────────
  class Snowflake {
    constructor(rotOffset, morphDelay) {
      this.angle   = rotOffset;
      this.atarget = rotOffset + Math.PI / 2;
      this.pieces  = [];
      this.build();
      setTimeout(() => this.morph(), morphDelay);
    }

    build() {
      this.pieces = [];
      let stroke = true;
      for (let r = 2; r <= 6; r++) {
        stroke = !stroke;
        const alpha  = Math.random() * 50 + 25;
        const offset = (Math.random() - 0.5) * 3.6;
        for (let i = 0; i < 6; i++) {
          const ang = i * Math.PI / 3;
          const x   = r * Math.cos(ang);
          const y   = r * Math.sin(ang);
          const br  = r / 1.5;
          this.pieces.push(new Piece(x, y, br + offset, br - offset, alpha, br, stroke));
        }
      }
      // Centre piece
      this.pieces.push(new Piece(0, 0, 0.5, 2, 75, 1, false));
    }

    morph() {
      this.atarget += Math.PI / 6;
      let offset = 0, alpha = 0;
      for (let i = 0; i < this.pieces.length; i++) {
        if (i % 6 === 0) {
          offset = (Math.random() - 0.5) * 3.6;
          alpha  = Math.random() * 75;
        }
        const p = this.pieces[i];
        p.ta  = alpha;
        p.tr1 = p.br + offset;
        p.tr2 = p.br - offset;
      }
      setTimeout(() => this.morph(), 2500 + Math.random() * 2000);
    }

    update() {
      this.angle = lerp(this.angle, this.atarget, 0.08);
      for (const p of this.pieces) p.shift();
    }

    draw(cx, cy, step) {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(this.angle);
      for (const p of this.pieces) p.draw(step);
      ctx.restore();
    }
  }

  let w = 0, h = 0;
  let flakes = null;

  function resize() {
    const nw = canvas.parentElement.offsetWidth;
    const nh = canvas.parentElement.offsetHeight;
    if (nw === w && nh === h) return;
    w = nw; h = nh;
    canvas.width  = w;
    canvas.height = h;
  }

  function animate() {
    resize();
    if (!w || !h) { requestAnimationFrame(animate); return; }

    // Lazy-init after we have dimensions
    if (!flakes) {
      flakes = [
        new Snowflake(0,              1000),
        new Snowflake(Math.PI / 6, 2500),
      ];
    }

    ctx.clearRect(0, 0, w, h);
    ctx.globalAlpha = 0.22;

    const step = h / 14;  // ring spacing — matches original h/20 scaled up slightly

    // Left flake: center 2 steps inside left edge, 40% down
    flakes[0].update();
    flakes[0].draw(-step * 1.5, h * 0.40, step);

    // Right flake: center 2 steps inside right edge, 62% down
    flakes[1].update();
    flakes[1].draw(w + step * 1.5, h * 0.62, step);

    requestAnimationFrame(animate);
  }

  animate();
})();
