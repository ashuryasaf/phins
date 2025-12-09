codeunit 50106 "PHINS User Management"
{
    /// <summary>
    /// Simple user management for PHINS (create, enable/disable, list)
    /// NOTE: This is a lightweight user store for demo/admin purposes only.
    /// In production use Business Central user/AD integration and permission sets.
    /// </summary>

    trigger OnRun()
    begin
    end;

    procedure CreateUser(UserID: Code[20]; Username: Text; FullName: Text; Email: Text; Role: Integer; PasswordHash: Text)
    var
        UserRec: Record "PHINS User Account";
    begin
        if UserRec.Get(UserID) then
            Error('User %1 already exists', UserID);

        UserRec.Init();
        UserRec."User ID" := UserID;
        UserRec.Username := Username;
        UserRec."Full Name" := FullName;
        UserRec.Email := Email;
        UserRec.Role := Role;
        UserRec.Active := true;
        UserRec."Password Hash" := PasswordHash;
        UserRec."Created Date" := CurrentDateTime();
        UserRec.Insert(true);
    end;

    procedure SetUserActive(UserID: Code[20]; IsActive: Boolean)
    var
        UserRec: Record "PHINS User Account";
    begin
        if not UserRec.Get(UserID) then
            Error('User %1 not found', UserID);

        UserRec.Active := IsActive;
        UserRec.Modify();
    end;

    procedure GetUserByUsername(Username: Text): Record "PHINS User Account"
    var
        UserRec: Record "PHINS User Account";
    begin
        UserRec.SetRange(Username, Username);
        if UserRec.FindFirst() then
            exit(UserRec)
        else
            Error('User %1 not found', Username);
    end;
}
