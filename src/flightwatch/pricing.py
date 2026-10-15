"""Bag cost completion and price classification."""

from .i18n import money, t

CATEGORIES = ["target", "good", "acceptable", "expensive"]


def label(category):
    return t("cat." + category)


def complete(offer, watch, cfg):
    """Add missing checked-bag cost so every offer is comparable 'inkl. bagage'."""
    pax = watch["adults"]
    want = watch["checked_bags_per_person"]
    bags = cfg.get("bags", {})
    carriers = bags.get("carriers", {})
    codes = offer.out.carrier_codes + offer.back.carrier_codes
    # Carrier-specific rule wins (first carrier we have a rule for).
    rule = next((carriers[c] for c in codes if c in carriers), {})
    included = offer.bags_included_pp
    if included is None:
        included = rule.get("included", bags.get("default_included_per_person", 1))
        offer.bag_cost_estimated = True
        assumed = t("bag.assume", n=included)
        offer.bag_note = (offer.bag_note + "; " if offer.bag_note else "") + assumed
    missing = max(0, want - included)
    if missing:
        fee = offer.extra_bag_fee
        if fee is None:
            fee = rule.get("extra_bag_sek", bags.get("extra_bag_sek", 1000))
            offer.bag_cost_estimated = True
        offer.bag_cost = round(missing * fee * pax * 2)
        offer.bag_note = (offer.bag_note + "; " if offer.bag_note else "") + \
            t("bag.extra", n=missing, fee=money(fee)) + (t("bag.estimated") if offer.bag_cost_estimated else "")
    offer.total = round(offer.ticket_total + offer.bag_cost + offer.fees)
    offer.per_person = round(offer.total / pax)
    offer.category = classify(offer.total, watch["thresholds"])
    return offer


def classify(total, t):
    if total <= t["target"]:
        return "target"
    if total <= t["good"]:
        return "good"
    if total <= t["acceptable"]:
        return "acceptable"
    return "expensive"
