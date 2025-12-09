page 50112 "PHINS Customer Premium Statement"
{
    PageType = Card;
    ApplicationArea = All;
    SourceTable = "PHINS Premium Allocation";
    Caption = 'Customer Premium Statement';

    layout
    {
        area(content)
        {
            group(Statement)
            {
                field("Customer ID"; "Customer ID") { }
                field("Premium Amount"; "Premium Amount") { }
                field("Risk Amount"; "Risk Amount") { }
                field("Savings Amount"; "Savings Amount") { }
                field(Status; Status) { }
                field("Posted Date"; "Posted Date") { }
            }
        }
    }
}
