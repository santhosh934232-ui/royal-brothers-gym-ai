/* ============================================
   ROYAL BROTHERS FITNESS GYM - AUTH CACHE
   Shared client-side cache + request de-duplication for the logged-in
   user's info from GET /api/auth/me.

   Why this exists:
   script.js (navbar), profile.js, and membership.js each independently
   called /api/auth/me on pages that include more than one of them
   (e.g. profile.html loads script.js AND profile.js; membership.html
   loads script.js AND membership.js). That produced two near-identical
   network requests per page load, and made the navbar wait on its own
   round trip before it could stop showing the logged-out Login/Join
   Now buttons -- which is the 1-2 second flicker to the Profile
   button that was reported.

   This module does two things, without changing what /api/auth/me
   returns or how the session/auth system works server-side:
     1. De-dupes requests: if two callers ask for the user at nearly
        the same time on the same page, they share one network call
        instead of firing two.
     2. Caches the last known result in sessionStorage (per browser
        tab, cleared when the tab closes) so that on the NEXT page
        navigation, the navbar can paint the logged-in state instantly
        from cache instead of waiting on the network -- eliminating
        the flicker on every navigation after the first.

   The cache is only ever used for instant UI paint. Every page load
   still calls fetchUser(), which always hits the real
   /api/auth/me endpoint and refreshes the cache -- so if a session
   has actually expired or changed, the UI corrects itself as soon as
   that call resolves, exactly as it always has.

   Include this script BEFORE script.js / profile.js / membership.js.
   ============================================ */

(function () {
  const CACHE_KEY = "rbfg_auth_user";
  // Short TTL: long enough to kill duplicate/rapid-navigation requests,
  // short enough that a real login/logout is never reflected stale for
  // more than a few seconds even before the background revalidation
  // fetch below has a chance to run.
  const CACHE_TTL_MS = 30 * 1000;

  let inFlightRequest = null;

  function readCache() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed.savedAt !== "number") return null;
      if (Date.now() - parsed.savedAt > CACHE_TTL_MS) return null;
      return parsed.result; // { ok, data } -- same shape /api/auth/me callers already expect
    } catch (err) {
      return null;
    }
  }

  function writeCache(result) {
    try {
      sessionStorage.setItem(
        CACHE_KEY,
        JSON.stringify({ savedAt: Date.now(), result }),
      );
    } catch (err) {
      // sessionStorage unavailable (private browsing, quota exceeded,
      // etc.) -- fail silently, the app still works without the cache.
    }
  }

  function clearCache() {
    try {
      sessionStorage.removeItem(CACHE_KEY);
    } catch (err) {
      // ignore
    }
  }

  /**
   * Returns whatever is currently cached for the logged-in user, or
   * null if nothing is cached / it has expired. Synchronous -- safe to
   * call immediately on page load, before any network request
   * resolves, so the navbar can paint instantly with no flicker.
   */
  function getCachedUser() {
    return readCache();
  }

  /**
   * Fetches /api/auth/me. No matter how many callers on the same page
   * call this at nearly the same time, only one real network request
   * is made -- everyone shares the same in-flight promise. Always hits
   * the network (this is the source of truth); the cache above is only
   * used for the instant-paint step via getCachedUser(). Resolves to
   * { ok, data } exactly like a direct fetch("/api/auth/me") did.
   */
  function fetchUser() {
    if (inFlightRequest) {
      return inFlightRequest;
    }

    inFlightRequest = fetch("/api/auth/me", { credentials: "include" })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then((result) => {
        if (result.ok && result.data && result.data.success) {
          writeCache(result);
        } else {
          clearCache();
        }
        return result;
      })
      .catch(() => {
        // Network failure -- don't touch the cache, let each caller
        // handle the failure the same way it always has.
        return { ok: false, data: null };
      })
      .finally(() => {
        inFlightRequest = null;
      });

    return inFlightRequest;
  }

  /**
   * Overwrites the cache directly with a known-fresh user object,
   * shaped the same way a successful /api/auth/me response is. Used
   * right after an action that changes the user's data server-side
   * (e.g. saving profile edits), so the cache can never show stale
   * information for longer than the TTL would otherwise allow.
   */
  function setCachedUser(user) {
    writeCache({ ok: true, data: { success: true, user } });
  }

  window.AuthCache = {
    getCachedUser,
    fetchUser,
    setCachedUser,
    clearCache,
  };
})();
