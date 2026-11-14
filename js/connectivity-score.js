/* =========================================================
   CONNECTIVITY SCORE CALCULATION
   Pure functions shared by the browser and Node tests
   ========================================================= */

/*
   Only finite, non-negative numbers are scored.
   Anything else (null, undefined, NaN, strings, negatives)
   is treated as a missing measurement.
*/

function isValidMetric(value) {
    return (
        typeof value === "number" &&
        Number.isFinite(value) &&
        value >= 0
    );
}


function calculateConnectivityScore(metrics) {

    if (!metrics) {
        return 0;
    }


    let score = 0;


    /* -----------------------------------------------------
       DOWNLOAD = 30 POINTS
       ----------------------------------------------------- */

    const download =
        metrics.download;


    if (isValidMetric(download)) {

        if (download >= 100) {
            score += 30;
        }

        else if (download >= 50) {
            score += 27;
        }

        else if (download >= 25) {
            score += 23;
        }

        else if (download >= 10) {
            score += 19;
        }

        else if (download >= 5) {
            score += 15;
        }

        else if (download >= 2) {
            score += 10;
        }

        else if (download >= 1) {
            score += 6;
        }

        else {
            score += 3;
        }
    }


    /* -----------------------------------------------------
       UPLOAD = 20 POINTS
       ----------------------------------------------------- */

    const upload =
        metrics.upload;


    if (isValidMetric(upload)) {

        if (upload >= 50) {
            score += 20;
        }

        else if (upload >= 25) {
            score += 18;
        }

        else if (upload >= 10) {
            score += 15;
        }

        else if (upload >= 5) {
            score += 12;
        }

        else if (upload >= 2) {
            score += 9;
        }

        else if (upload >= 1) {
            score += 6;
        }

        else {
            score += 2;
        }
    }


    /* -----------------------------------------------------
       PING = 20 POINTS
       ----------------------------------------------------- */

    const ping =
        metrics.ping;


    if (isValidMetric(ping)) {

        if (ping <= 20) {
            score += 20;
        }

        else if (ping <= 40) {
            score += 18;
        }

        else if (ping <= 60) {
            score += 16;
        }

        else if (ping <= 100) {
            score += 13;
        }

        else if (ping <= 150) {
            score += 10;
        }

        else if (ping <= 200) {
            score += 7;
        }

        else if (ping <= 300) {
            score += 4;
        }

        else {
            score += 1;
        }
    }


    /* -----------------------------------------------------
       JITTER = 20 POINTS
       ----------------------------------------------------- */

    const jitter =
        metrics.jitter;


    if (isValidMetric(jitter)) {

        if (jitter <= 5) {
            score += 20;
        }

        else if (jitter <= 10) {
            score += 17;
        }

        else if (jitter <= 20) {
            score += 14;
        }

        else if (jitter <= 30) {
            score += 11;
        }

        else if (jitter <= 50) {
            score += 8;
        }

        else if (jitter <= 100) {
            score += 5;
        }

        else {
            score += 2;
        }
    }


    /* -----------------------------------------------------
       PACKET LOSS = 10 POINTS
       ----------------------------------------------------- */

    const packetLoss =
        metrics.packetLoss;


    if (isValidMetric(packetLoss)) {

        if (packetLoss <= 0.5) {
            score += 10;
        }

        else if (packetLoss <= 1) {
            score += 8;
        }

        else if (packetLoss <= 2) {
            score += 6;
        }

        else if (packetLoss <= 5) {
            score += 3;
        }
    }


    /*
       Maximum = 100
    */

    return Math.round(
        Math.max(
            0,
            Math.min(
                100,
                score
            )
        )
    );
}


function getConnectivityStatus(score) {

    let status = "Poor";


    if (
        score >= 85
    ) {
        status = "Excellent";
    }

    else if (
        score >= 70
    ) {
        status = "Good";
    }

    else if (
        score >= 50
    ) {
        status = "Average";
    }


    return status;
}


if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        isValidMetric,
        calculateConnectivityScore,
        getConnectivityStatus
    };
}
