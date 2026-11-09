import asyncio

async def verify_telemetry(provider, simulation=True, interval=60):
    samples=[]
    for i in range(4):
        if i and not simulation:
            await asyncio.sleep(interval)
        sample=provider.metrics()
        if asyncio.iscoroutine(sample):
            sample=await sample
        samples.append(sample)
    checks={"memory":all(s.get("memory_gib",float("inf"))<1.2 for s in samples),
        "pool":all(s.get("pool_utilization",1)<0.8 for s in samples),
        "evictions":all(s.get("evictions_per_second",1)==0 for s in samples),
        "five_xx_burn":all(s.get("five_xx_burn",float("inf"))<1 for s in samples),
        "restarts":all(s.get("restart_delta",1)==0 for s in samples),
        "readiness":all(s.get("ready") is True for s in samples),
        "independent_samples":len({s.get("sample") for s in samples})==4,
        "source":simulation or all(s.get("source")=="live" for s in samples)}
    return {"passed":all(checks.values()),"checks":checks,"samples":samples,
        "window_seconds":0 if simulation else interval*3,"simulated":simulation}
