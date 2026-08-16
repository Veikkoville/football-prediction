/* Creator ref bridge for goaliq.app (16.8.2026).
 *
 * WHY THIS EXISTS
 * Affiliate attribution is captured in the SPA at pro.goaliq.app, which stores
 * the ref in localStorage and attaches it to the account at sign-up. That works
 * only if the visitor lands on pro.goaliq.app carrying ?ref=.
 *
 * Creators do not link that way. They link to the page that reads best, which
 * is goaliq.app or goaliq.app/fpl. Those are a DIFFERENT ORIGIN, so anything
 * stored here is invisible to the SPA: same-origin storage is not a detail we
 * can work around, it is the rule. A creator who posted goaliq.app/fpl?ref=X
 * was getting nothing at all, and neither of us could see that happening.
 *
 * So the ref is not stored for the SPA, it is CARRIED to it. Two jobs:
 *   1. remember the ref while the visitor moves around goaliq.app
 *   2. append it to every link that leaves for pro.goaliq.app
 *
 * Deliberately dependency-free and defensive: this runs on every hub page, and
 * a throw here would take the page's other scripts with it. Every branch fails
 * to "do nothing" rather than to an error.
 */
(function () {
	'use strict';

	var KEY = 'giq:ref';
	// Same rule as the SPA's cleanRef and the backend's _clean_affiliate_ref.
	// Three copies of one regex is a smell, but they live in three languages on
	// three origins, and a mismatch would fail silently in exactly the way this
	// whole file exists to prevent. Keep them identical.
	var RE = /^[A-Z0-9_-]{2,32}$/;
	var SPA_HOST = 'pro.goaliq.app';

	function clean(v) {
		if (typeof v !== 'string') return null;
		var s = v.trim().toUpperCase();
		return RE.test(s) ? s : null;
	}

	function stored() {
		try {
			return clean(localStorage.getItem(KEY));
		} catch (e) {
			return null;
		}
	}

	function capture() {
		var found = null;
		try {
			found = clean(new URLSearchParams(location.search).get('ref'));
		} catch (e) {
			found = null;
		}
		// First writer wins, same as the SPA: the creator who actually brought
		// the visitor keeps the attribution, and a later link cannot take it.
		if (found) {
			try {
				if (!localStorage.getItem(KEY)) localStorage.setItem(KEY, found);
			} catch (e) {
				/* storage blocked; the in-page rewrite below still works */
			}
		}
		return found || stored();
	}

	var REF = capture();
	if (!REF) return;

	function withRef(href) {
		try {
			var u = new URL(href, location.href);
			if (u.hostname !== SPA_HOST) return null;
			// Never overwrite an explicit ref already on the link.
			if (u.searchParams.get('ref')) return null;
			u.searchParams.set('ref', REF);
			return u.toString();
		} catch (e) {
			return null;
		}
	}

	function rewriteAll() {
		var links = document.querySelectorAll('a[href]');
		for (var i = 0; i < links.length; i++) {
			var next = withRef(links[i].getAttribute('href'));
			if (next) links[i].setAttribute('href', next);
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', rewriteAll);
	} else {
		rewriteAll();
	}

	// Click-time fallback. The pass above covers the markup as shipped, but a
	// link added later by another script would miss it, and a missed link is
	// invisible: the visitor still arrives, just unattributed. Capture phase so
	// this runs before any handler that might navigate.
	document.addEventListener(
		'click',
		function (ev) {
			var el = ev.target;
			while (el && el.tagName !== 'A') el = el.parentElement;
			if (!el) return;
			var next = withRef(el.getAttribute('href'));
			if (next) el.setAttribute('href', next);
		},
		true
	);
})();
