const MAX_PRICE = 1000;

const PAGE_SIZE = 30;

let allListings = [];

let filteredListings = [];

let currentPage = 1;


const elements = {
    search: document.getElementById("search"),

    marketplace: document.getElementById(
        "marketplace"
    ),

    status: document.getElementById(
        "status"
    ),

    price: document.getElementById(
        "price"
    ),

    sort: document.getElementById(
        "sort"
    ),

    listings: document.getElementById(
        "listings"
    ),

    resultCount: document.getElementById(
        "resultCount"
    ),

    pagination: document.getElementById(
        "pagination"
    ),

    loading: document.getElementById(
        "loading"
    ),

    error: document.getElementById(
        "error"
    ),

    errorMessage: document.getElementById(
        "errorMessage"
    ),

    empty: document.getElementById(
        "empty"
    ),

    totalListings: document.getElementById(
        "totalListings"
    ),

    verifiedListings: document.getElementById(
        "verifiedListings"
    ),

    dealListings: document.getElementById(
        "dealListings"
    ),

    underBudget: document.getElementById(
        "underBudget"
    ),

    lastUpdated: document.getElementById(
        "lastUpdated"
    )
};


function parseCSV(text) {

    const rows = [];

    let row = [];

    let cell = "";

    let insideQuotes = false;


    for (let i = 0; i < text.length; i++) {

        const character = text[i];

        const next = text[i + 1];


        if (
            character === '"' &&
            insideQuotes &&
            next === '"'
        ) {
            cell += '"';

            i++;

            continue;
        }


        if (character === '"') {
            insideQuotes = !insideQuotes;

            continue;
        }


        if (
            character === "," &&
            !insideQuotes
        ) {
            row.push(cell);

            cell = "";

            continue;
        }


        if (
            (
                character === "\n" ||
                character === "\r"
            ) &&
            !insideQuotes
        ) {

            if (
                character === "\r" &&
                next === "\n"
            ) {
                i++;
            }

            row.push(cell);

            cell = "";


            if (
                row.some(
                    value =>
                        value.trim() !== ""
                )
            ) {
                rows.push(row);
            }

            row = [];

            continue;
        }


        cell += character;
    }


    if (cell !== "" || row.length > 0) {

        row.push(cell);

        rows.push(row);
    }


    if (rows.length < 2) {
        return [];
    }


    const headers = rows[0].map(
        header =>
            header.trim()
    );


    return rows
        .slice(1)
        .map(values => {

            const object = {};

            headers.forEach(
                (header, index) => {

                    object[header] =
                        (
                            values[index] ||
                            ""
                        ).trim();

                }
            );

            return object;

        });
}


function escapeHTML(value) {

    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function numberValue(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }


    const number =
        Number.parseFloat(value);


    if (Number.isNaN(number)) {
        return null;
    }


    return number;
}


function isVerified(listing) {

    return (
        String(
            listing.verified
        ).toLowerCase() === "true"
    );
}


function isDeal(listing) {

    const deal =
        String(
            listing.deal || ""
        ).toLowerCase();


    return (
        deal.includes("deal") &&
        isVerified(listing)
    );
}


function updateStats() {

    const total =
        allListings.length;


    const verified =
        allListings.filter(
            isVerified
        ).length;


    const deals =
        allListings.filter(
            isDeal
        ).length;


    const underBudget =
        allListings.filter(
            listing => {

                const price =
                    numberValue(
                        listing.price_pln
                    );

                return (
                    price !== null &&
                    price <= MAX_PRICE
                );

            }
        ).length;


    elements.totalListings.textContent =
        total.toLocaleString();


    elements.verifiedListings.textContent =
        verified.toLocaleString();


    elements.dealListings.textContent =
        deals.toLocaleString();


    elements.underBudget.textContent =
        underBudget.toLocaleString();
}


function populateMarketplaces() {

    const marketplaces =
        [
            ...new Set(
                allListings
                    .map(
                        listing =>
                            listing.marketplace
                    )
                    .filter(Boolean)
            )
        ]
        .sort();


    for (
        const marketplace of marketplaces
    ) {

        const option =
            document.createElement(
                "option"
            );


        option.value =
            marketplace;


        option.textContent =
            marketplace;


        elements.marketplace.appendChild(
            option
        );
    }
}


function applyFilters() {

    const search =
        elements.search.value
            .trim()
            .toLowerCase();


    const marketplace =
        elements.marketplace.value;


    const status =
        elements.status.value;


    const maxPrice =
        elements.price.value;


    const sort =
        elements.sort.value;


    filteredListings =
        allListings.filter(
            listing => {

                const searchable =
                    (
                        String(
                            listing.title || ""
                        ) +
                        " " +
                        String(
                            listing.url || ""
                        ) +
                        " " +
                        String(
                            listing.marketplace || ""
                        )
                    ).toLowerCase();


                if (
                    search &&
                    !searchable.includes(
                        search
                    )
                ) {
                    return false;
                }


                if (
                    marketplace !== "all" &&
                    listing.marketplace !==
                        marketplace
                ) {
                    return false;
                }


                if (
                    status === "verified" &&
                    !isVerified(listing)
                ) {
                    return false;
                }


                if (
                    status === "rejected" &&
                    isVerified(listing)
                ) {
                    return false;
                }


                if (
                    maxPrice !== "all"
                ) {

                    const price =
                        numberValue(
                            listing.price_pln
                        );


                    if (
                        price === null ||
                        price >
                            Number(maxPrice)
                    ) {
                        return false;
                    }
                }


                return true;
            }
        );


    filteredListings.sort(
        (a, b) => {

            if (sort === "score") {

                return (
                    numberValue(
                        b.score
                    ) -
                    numberValue(
                        a.score
                    )
                );
            }


            if (
                sort === "price-low"
            ) {

                return (
                    (
                        numberValue(
                            a.price_pln
                        ) ??
                        Number.POSITIVE_INFINITY
                    ) -
                    (
                        numberValue(
                            b.price_pln
                        ) ??
                        Number.POSITIVE_INFINITY
                    )
                );
            }


            if (
                sort === "price-high"
            ) {

                return (
                    (
                        numberValue(
                            b.price_pln
                        ) ??
                        -1
                    ) -
                    (
                        numberValue(
                            a.price_pln
                        ) ??
                        -1
                    )
                );
            }


            return (
                String(
                    b.timestamp || ""
                ).localeCompare(
                    String(
                        a.timestamp || ""
                    )
                )
            );

        }
    );


    currentPage = 1;

    render();
}


function createListingCard(
    listing
) {

    const verified =
        isVerified(listing);


    const price =
        numberValue(
            listing.price_pln
        );


    const score =
        numberValue(
            listing.score
        );


    const deal =
        listing.deal || "";


    const title =
        listing.title ||
        "Untitled listing";


    const marketplace =
        listing.marketplace ||
        "Unknown";


    const reason =
        listing.verification_reason ||
        "";


    const url =
        listing.final_url ||
        listing.url ||
        "#";


    const priceHTML =
        price !== null
            ? `
                <span class="tag price">
                    💰 ${price.toFixed(2)} PLN
                </span>
              `
            : `
                <span class="tag">
                    💰 No price
                </span>
              `;


    const scoreHTML =
        score !== null
            ? `
                <span class="tag score">
                    ⭐ ${score}
                </span>
              `
            : "";


    const dealHTML =
        deal &&
        deal !== "CHECK" &&
        deal !== "NO PRICE"
            ? `
                <span class="tag deal">
                    ${escapeHTML(deal)}
                </span>
              `
            : "";


    const statusHTML =
        verified
            ? `
                <span class="tag verified">
                    ✅ Verified
                </span>
              `
            : `
                <span class="tag rejected">
                    ❌ Rejected
                </span>
              `;


    const reasonHTML =
        reason
            ? `
                <span class="reason">
                    ${escapeHTML(reason)}
                </span>
              `
            : "";


    return `
        <article class="listing">

            <div class="listing-top">

                <h3 class="listing-title">

                    <a
                        href="${escapeHTML(url)}"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        ${escapeHTML(title)}
                    </a>

                </h3>

                <span class="marketplace">
                    ${escapeHTML(marketplace)}
                </span>

            </div>


            <div class="listing-info">

                ${priceHTML}

                ${scoreHTML}

                ${dealHTML}

                ${statusHTML}

            </div>


            <div class="listing-bottom">

                ${reasonHTML}

                <a
                    class="open-link"
                    href="${escapeHTML(url)}"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    Open listing ↗
                </a>

            </div>

        </article>
    `;
}


function render() {

    elements.loading.hidden = true;

    elements.error.hidden = true;


    const total =
        filteredListings.length;


    elements.resultCount.textContent =
        `${total.toLocaleString()} result${
            total === 1 ? "" : "s"
        }`;


    if (total === 0) {

        elements.listings.innerHTML = "";

        elements.empty.hidden = false;

        elements.pagination.innerHTML = "";

        return;
    }


    elements.empty.hidden = true;


    const totalPages =
        Math.ceil(
            total / PAGE_SIZE
        );


    if (
        currentPage >
        totalPages
    ) {
        currentPage =
            totalPages;
    }


    const start =
        (
            currentPage - 1
        ) *
        PAGE_SIZE;


    const end =
        start +
        PAGE_SIZE;


    const pageListings =
        filteredListings.slice(
            start,
            end
        );


    elements.listings.innerHTML =
        pageListings
            .map(
                createListingCard
            )
            .join("");


    renderPagination(
        totalPages
    );
}


function renderPagination(
    totalPages
) {

    elements.pagination.innerHTML = "";


    if (totalPages <= 1) {
        return;
    }


    const previous =
        document.createElement(
            "button"
        );


    previous.textContent =
        "‹";


    previous.disabled =
        currentPage === 1;


    previous.addEventListener(
        "click",
        () => {

            currentPage--;

            render();

            window.scrollTo({
                top: 0,
                behavior: "smooth"
            });

        }
    );


    elements.pagination.appendChild(
        previous
    );


    const start =
        Math.max(
            1,
            currentPage - 2
        );


    const end =
        Math.min(
            totalPages,
            currentPage + 2
        );


    for (
        let page = start;
        page <= end;
        page++
    ) {

        const button =
            document.createElement(
                "button"
            );


        button.textContent =
            page;


        if (
            page === currentPage
        ) {
            button.classList.add(
                "active"
            );
        }


        button.addEventListener(
            "click",
            () => {

                currentPage =
                    page;

                render();

                window.scrollTo({
                    top: 0,
                    behavior: "smooth"
                });

            }
        );


        elements.pagination.appendChild(
            button
        );
    }


    const next =
        document.createElement(
            "button"
        );


    next.textContent =
        "›";


    next.disabled =
        currentPage ===
        totalPages;


    next.addEventListener(
        "click",
        () => {

            currentPage++;

            render();

            window.scrollTo({
                top: 0,
                behavior: "smooth"
            });

        }
    );


    elements.pagination.appendChild(
        next
    );
}


async function loadResults() {

    try {

        const response =
            await fetch(
                `results.csv?t=${Date.now()}`
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const text =
            await response.text();


        allListings =
            parseCSV(text);


        updateStats();

        populateMarketplaces();

        applyFilters();


        if (
            allListings.length > 0
        ) {

            const timestamps =
                allListings
                    .map(
                        listing =>
                            listing.timestamp
                    )
                    .filter(Boolean)
                    .sort();


            if (
                timestamps.length
            ) {

                const latest =
                    timestamps[
                        timestamps.length - 1
                    ];


                const date =
                    new Date(latest);


                if (
                    !Number.isNaN(
                        date.getTime()
                    )
                ) {

                    elements.lastUpdated.textContent =
                        "Last result: " +
                        date.toLocaleString();

                }
            }
        }

    } catch (error) {

        elements.loading.hidden =
            true;

        elements.error.hidden =
            false;

        elements.errorMessage.textContent =
            error.message;

    }
}


elements.search.addEventListener(
    "input",
    applyFilters
);


elements.marketplace.addEventListener(
    "change",
    applyFilters
);


elements.status.addEventListener(
    "change",
    applyFilters
);


elements.price.addEventListener(
    "change",
    applyFilters
);


elements.sort.addEventListener(
    "change",
    applyFilters
);


loadResults();
