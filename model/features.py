from collections import defaultdict, deque
import math

FORMATS = ["ACH", "Bitcoin", "Cash", "Cheque", "Credit Card", "Reinvestment", "Wire"]
CURRENCIES = ["Australian Dollar", "Bitcoin", "Brazil Real", "Canadian Dollar", "Euro", "Mexican Peso",
              "Ruble", "Rupee", "Saudi Riyal", "Shekel", "Swiss Franc", "UK Pound", "US Dollar", "Yen", "Yuan"]
WIN = 60  # minutes of history to look at

TXN_FEATURES = ["log_amt", "self_txn", "cross_cur", "fmt", "hour", "round_amt"]
NET_FEATURES = ["dst_in_senders", "dst_in_count", "dst_burst_10m", "dst_in_amt_log",
                "src_out_receivers", "src_out_count", "src_in_amt_log",
                "fwd_ratio", "fwd_lag", "src_first_seen", "dst_first_seen",
                "pair_seen", "cycle2", "cycle3"]
ALL_FEATURES = TXN_FEATURES + NET_FEATURES


class FlowState:
    """Remembers recent money movement per account. Features use ONLY the past."""

    def __init__(self, win=WIN):
        self.win = win
        self.inn = defaultdict(deque)   # account -> (time, sender, amount) received
        self.out = defaultdict(deque)   # account -> (time, receiver, amount) sent
        self.seen = set()
        self.pairs = set()
        self.last_in = {}

    def _recent(self, dq, t):
        while dq and dq[0][0] < t - self.win:
            dq.popleft()
        return dq

    def features(self, t, src, dst, amount, cur_paid, cur_recv, fmt):
        din = self._recent(self.inn[dst], t)
        dout = self._recent(self.out[dst], t)
        sin = self._recent(self.inn[src], t)
        sout = self._recent(self.out[src], t)
        dst_senders = {x[1] for x in din}
        src_receivers = {x[1] for x in sout}
        dst_receivers = {x[1] for x in dout}
        src_in_amt = sum(x[2] for x in sin)
        src_out_amt = sum(x[2] for x in sout) + amount
        cycle2 = 1 if src in dst_receivers else 0
        cycle3 = 0
        if not cycle2:
            for r in sorted(dst_receivers)[:20]:   # sorted: set order changes between processes
                ro = self.out.get(r)
                if ro and any(x[1] == src and x[0] >= t - self.win for x in ro):
                    cycle3 = 1
                    break
        lag = t - self.last_in[src] if src in self.last_in else 1440
        return {
            "log_amt": math.log1p(max(amount, 0)),
            "self_txn": 1 if src == dst else 0,
            "cross_cur": 1 if cur_paid != cur_recv else 0,
            "fmt": FORMATS.index(fmt) if fmt in FORMATS else -1,
            "hour": (t // 60) % 24,
            "round_amt": 1 if amount >= 100 and amount == int(amount) else 0,
            "dst_in_senders": len(dst_senders),
            "dst_in_count": len(din),
            "dst_burst_10m": sum(1 for x in din if x[0] >= t - 10),
            "dst_in_amt_log": math.log1p(sum(x[2] for x in din)),
            "src_out_receivers": len(src_receivers),
            "src_out_count": len(sout),
            "src_in_amt_log": math.log1p(src_in_amt),
            "fwd_ratio": min(src_out_amt / src_in_amt, 50) if src_in_amt > 0 else 0,
            "fwd_lag": min(lag, 1440),
            "src_first_seen": 0 if src in self.seen else 1,
            "dst_first_seen": 0 if dst in self.seen else 1,
            "pair_seen": 1 if (src, dst) in self.pairs else 0,
            "cycle2": cycle2,
            "cycle3": cycle3,
        }

    def update(self, t, src, dst, amount):
        self.out[src].append((t, dst, amount))
        self.inn[dst].append((t, src, amount))
        self.pairs.add((src, dst))
        self.seen.add(src)
        self.seen.add(dst)
        self.last_in[dst] = t


def reasons(f):
    """Plain-English reasons an analyst can read."""
    r = []
    if f["dst_in_senders"] >= 5:
        r.append(f"Receiver got money from {int(f['dst_in_senders'])} different accounts in the last hour")
    if f["fwd_ratio"] >= 0.8 and f["fwd_lag"] <= 60:
        r.append(f"Sender is passing on {min(f['fwd_ratio'], 1) * 100:.0f}% of money it received {int(f['fwd_lag'])} min ago")
    if f["src_out_receivers"] >= 5:
        r.append(f"Sender paid {int(f['src_out_receivers'])} different accounts in the last hour")
    if f["cycle2"]:
        r.append("Money is flowing back to the sender (2-account loop)")
    if f["cycle3"]:
        r.append("Money returns to the sender through a 3-account loop")
    if f["dst_burst_10m"] >= 3:
        r.append(f"{int(f['dst_burst_10m'])} payments hit the receiver within 10 minutes")
    if f["dst_first_seen"]:
        r.append("Receiving account has never been seen before")
    return r[:4]


def rule_score(f):
    """Baseline B: simple hand-written rules, no machine learning."""
    s = min(f["dst_in_senders"], 10) / 10 * 0.3
    s += 0.3 if (f["fwd_ratio"] >= 0.8 and f["fwd_lag"] <= 60) else 0
    s += min(f["src_out_receivers"], 10) / 10 * 0.2
    s += 0.2 if (f["cycle2"] or f["cycle3"]) else 0
    return s
