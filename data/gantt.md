gantt
    title Gav Yam Clinical Operations
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Pre-Study Setup
    Gav Yam office / study station ready           :crit, setup1, 2026-03-30, 2w
    Network router + ISP + static IP               :setup2, after setup1, 1w
    GCS firewall whitelist static IP               :setup3, after setup2, 2d
    Pavel Apple Watch interference test            :pavel, 2026-03-30, 3w
    Food procurement and portion standardization   :food, 2026-04-06, 2w
    Source CGMs for control subjects               :cgm, 2026-04-06, 2w
    Wire routing and subject comfort validation    :wire, after setup1, 1w
    Recording system setup + bench test            :bench, after setup1, 1w

    section Readiness Gate
    All pre-study items complete                   :milestone, gate0, 2026-04-27, 0d

    section Phase A - Dual Sensor (Subjects 1-5)
    Subject 1 dual Nivio + Nivio-S                 :crit, s1, 2026-04-27, 3d
    Subject 2                                      :s2, after s1, 4d
    Subject 3                                      :s3, after s2, 4d
    Subject 4                                      :s4, after s3, 4d
    Subject 5                                      :s5, after s4, 4d
    Concordance review Nivio vs Nivio-S            :crit, conc, after s5, 3d
    Meal 2 timing review                           :meal_review, after s5, 3d

    section Phase B - Nivio-S Only (Subjects 6-25)
    Subjects 6-10                                  :b1, after conc, 3w
    Subjects 11-15                                 :b2, after b1, 3w
    Subjects 16-20                                 :b3, after b2, 3w
    Subjects 21-25                                 :b4, after b3, 3w
    Study complete                                 :milestone, done, after b4, 0d