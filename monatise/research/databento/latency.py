"""Fixed-memory latency histograms, price-free and independent of wall clocks."""
import threading


class Latencies:
    def __init__(self):self._lock=threading.Lock();self._values={}

    def record(self,name,ns):
        ns=max(0,int(ns));bucket=min(63,ns.bit_length())
        with self._lock:
            entry=self._values.setdefault(name,dict(count=0,total_ns=0,max_ns=0,buckets=[0]*64))
            entry['count']+=1;entry['total_ns']+=ns;entry['max_ns']=max(entry['max_ns'],ns);entry['buckets'][bucket]+=1

    def summary(self):
        with self._lock:
            result={}
            for name,e in self._values.items():
                row={k:e[k] for k in ('count','max_ns')};row['mean_ns']=e['total_ns']//e['count']
                for label,fraction in (('p50',.5),('p95',.95),('p99',.99)):
                    count=0
                    for i,n in enumerate(e['buckets']):
                        count+=n
                        if count>=e['count']*fraction:row[label+'_upper_ns']=min(e['max_ns'],2**i);break
                result[name]=row
            return result
