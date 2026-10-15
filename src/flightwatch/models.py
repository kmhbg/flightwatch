from dataclasses import dataclass, field, asdict


@dataclass
class Leg:
    """One direction (outbound or inbound) of a trip."""
    depart: str = ""            # ISO local time "2026-12-19T15:05"
    arrive: str = ""
    duration_min: int = 0
    stops: int = 0
    via: list = field(default_factory=list)       # layover airports/cities
    layovers_min: list = field(default_factory=list)
    carriers: list = field(default_factory=list)  # airline names
    carrier_codes: list = field(default_factory=list)
    self_transfer: bool = False  # bags must be rechecked / separate tickets


@dataclass
class Offer:
    source: str                 # kiwi | google | ving | apollo
    kind: str                   # flight | package
    origin: str
    destination: str
    depart_date: str
    return_date: str
    ticket_total: float         # what the source quotes for all travellers
    currency: str = "SEK"
    out: Leg = field(default_factory=Leg)
    back: Leg = field(default_factory=Leg)
    bags_included_pp: int | None = None   # checked bags/person/direction already in ticket_total
    extra_bag_fee: float | None = None    # source-quoted price per extra bag per direction
    bag_cost: float = 0.0                 # extra for missing checked bags (all pax, both directions)
    bag_cost_estimated: bool = False
    bag_note: str = ""
    fees: float = 0.0                     # other mandatory fees not in ticket_total
    total: float = 0.0                    # ticket_total + bag_cost + fees
    per_person: float = 0.0
    out_price: float | None = None        # when the source prices directions separately
    back_price: float | None = None
    url: str = ""
    booking_via: str = ""                 # who sells it (Kiwi.com, Ving, airline...)
    tickets: int = 1                      # separate PNRs (self-transfer risk when > 1)
    conditions: str = ""                  # ticket conditions / warnings
    booking_options: list = field(default_factory=list)  # [{"who", "price", "airline"}] from Google
    hotel: str = ""                       # packages only
    category: str = ""                    # target | good | acceptable | expensive
    seen_at: str = ""

    @property
    def max_stops(self):
        return max(self.out.stops, self.back.stops)

    @property
    def airlines(self):
        names = []
        for n in self.out.carriers + self.back.carriers:
            if n and n not in names:
                names.append(n)
        return names

    def key(self):
        """Stable identity used for de-duplication within a run."""
        return (self.source, self.kind, self.origin, self.depart_date, self.return_date,
                self.out.depart, self.back.depart, "/".join(self.airlines), self.hotel)

    def to_dict(self):
        d = asdict(self)
        d["max_stops"] = self.max_stops
        d["airlines"] = self.airlines
        return d
