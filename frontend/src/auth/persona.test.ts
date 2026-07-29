import { describe, expect, it } from "vitest";
import { FALLBACK_PROFILE, coercePersona, homePathFor, navFor } from "./persona";

describe("persona helpers", () => {
  it("coerces unknown persona to operator", () => {
    expect(coercePersona(undefined)).toBe("operator");
    expect(coercePersona("boss")).toBe("operator");
    expect(coercePersona("executive")).toBe("executive");
  });

  it("resolves landings for the three product personas", () => {
    expect(homePathFor("executive", FALLBACK_PROFILE)).toBe("/discover?mode=scientific");
    expect(homePathFor("researcher", FALLBACK_PROFILE)).toBe(
      "/discover?mode=scientific&focus=evidence",
    );
    expect(homePathFor("operator", FALLBACK_PROFILE)).toBe("/");
  });

  it("resolves nav items from the customer profile", () => {
    expect(navFor("executive", FALLBACK_PROFILE)).toEqual(["discover", "home"]);
    expect(navFor("operator", FALLBACK_PROFILE)).toEqual(["home", "new"]);
  });
});
