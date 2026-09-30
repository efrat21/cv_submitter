def run():

    cv = load_cv("cv.txt")

    jobs = devbg.get_jobs(JOBS_URL)
    
    dashboard.show(jobs)

    for job in jobs:

        if database.already_processed(job.url):
            continue

        if not deterministic_filter(job):
            database.save_rejected(job)
            continue

        evaluation = llm.evaluate(
            cv=cv,
            job=job
        )

        database.save_evaluation(
            job,
            evaluation
        )

        if not evaluation.suitable:
            continue

        letter = llm.generate_cover_letter(
            cv=cv,
            job=job,
            evaluation=evaluation
        )

        if MODE == "DRY_RUN":
            continue

        application.fill(
            job=job,
            cv=cv,
            cover_letter=letter
        )

        if MODE == "REVIEW":
            wait_for_user()

        application.submit()

        database.mark_submitted(job)