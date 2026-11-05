"""Hash-bound calendar reviews, bounded coverage, no invented events or completeness."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from hashlib import sha256
import json
from monatise.research.unified.models import News,digest
REQUIRED=('BLS','FED','BEA','DOL','ISM')
DOMAINS={'BLS':('bls.gov',),'FED':('federalreserve.gov',),'BEA':('bea.gov',),
         'DOL':('dol.gov',),'ISM':('ismworld.org',)}
@dataclass(frozen=True)
class CalendarSource:
    publisher:str
    url:str
    evidence_path:str
    sha256:str
    retrieved_ns:int
    start_ns:int
    end_ns:int
    complete:bool
    events:tuple[News,...]=()
    def verify(self,cutoff):
        host=urlparse(self.url).hostname or ''
        if self.publisher not in DOMAINS or not any(host==d or host.endswith('.'+d) for d in DOMAINS[self.publisher]):raise ValueError('OFFICIAL_CALENDAR_SOURCE_REQUIRED')
        if not 0<self.start_ns<self.end_ns or not 0<self.retrieved_ns<=cutoff or type(self.complete) is not bool:raise ValueError('CAUSAL_BOUNDED_CALENDAR_REVIEW_REQUIRED')
        p=Path(self.evidence_path)
        if p.is_symlink() or not p.is_file() or p.stat().st_size>8*1024**2 or sha256(p.read_bytes()).hexdigest()!=self.sha256:raise ValueError('CALENDAR_SOURCE_HASH_MISMATCH')
        for n in self.events:
            if (not self.start_ns<=n.start_ns<n.end_ns<=self.end_ns or n.available_ns<self.retrieved_ns
                or n.available_ns>cutoff or n.source!=self.url or not n.event):raise ValueError('CAUSAL_SOURCED_EVENT_REQUIRED')
        return True
@dataclass(frozen=True)
class NewsReview:
    sources:tuple[CalendarSource,...]=()
    # This defines scheduled-calendar scope, never complete geopolitical/unscheduled news.
    required_publishers:tuple[str,...]=REQUIRED
    def __post_init__(self):
        if tuple(self.required_publishers)!=REQUIRED:raise ValueError('REQUIRED_CALENDAR_SCOPE_CANNOT_BE_SILENTLY_REDUCED')
    def status(self,cutoff):
        valid=[];errors=[]
        for s in self.sources:
            try:s.verify(cutoff);valid.append(s)
            except (ValueError,OSError) as exc:errors.append({'publisher':s.publisher,'reason':str(exc)})
        missing=[p for p in self.required_publishers if not any(s.publisher==p and s.complete and s.start_ns<=cutoff<s.end_ns for s in valid)]
        events=tuple({digest(n):n for s in valid for n in s.events if n.available_ns<=cutoff}.values())
        blocked=[n.event for n in events if n.start_ns<=cutoff<n.end_ns]
        reasons=(['NEWS_CALENDAR_UNAVAILABLE'] if missing or errors else [])+(['SCHEDULED_NEWS_WINDOW'] if blocked else [])
        return {'available':not missing and not errors,'reasons':reasons,'missing_publishers':missing,'source_errors':errors,'active_events':blocked,'events':events,'scope':'REVIEWED_SCHEDULED_US_CALENDARS_ONLY_UNSCHEDULED_NEWS_NOT_CERTIFIED','review_hash':digest(self)}

def load_review(path):
    x=json.loads(Path(path).read_text());sources=[]
    for s in x.get('sources',[]):
        y=dict(s);y['events']=tuple(News(**n) for n in y.get('events',[]));sources.append(CalendarSource(**y))
    return NewsReview(tuple(sources))
