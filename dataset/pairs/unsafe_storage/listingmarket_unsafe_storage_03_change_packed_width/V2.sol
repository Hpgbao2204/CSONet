// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

abstract contract EpochState {
    uint128 internal inheritedEpoch;
}

abstract contract GuardianState {
    address internal guardian;
}

contract ListingMarket is EpochState, GuardianState {
    address public owner;
    uint256 public total;
    uint128 public limit;
    bool public active;
    mapping(address => uint256) public purchases;
    uint256[4] private __gap;

    event Initialized(address indexed owner);
    event ValueAdded(address indexed account, uint256 amount, uint256 total);
    event ValueRemoved(address indexed account, uint256 amount, uint256 total);
    event LimitChanged(uint128 newLimit);
    event ActiveChanged(bool active);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    function initialize(address initialOwner, uint128 initialLimit) external {
        require(owner == address(0), "initialized");
        owner = initialOwner;
        guardian = initialOwner;
        limit = initialLimit;
        active = true;
        emit Initialized(initialOwner);
    }

    function buyListing(uint256 amount) external returns (uint256) {
        require(active, "inactive");
        require(amount <= uint256(limit), "over limit");
        uint256 next = total + amount;
        total = next;
        purchases[msg.sender] += amount;
        emit ValueAdded(msg.sender, amount, total);
        return total;
    }

    function withdraw(address account, uint256 amount) external onlyOwner returns (uint256) {
        require(purchases[account] >= amount, "insufficient");
        purchases[account] -= amount;
        total -= amount;
        (bool ok, ) = payable(owner).call{value: amount}("");
        require(ok, "transfer failed");
        emit ValueRemoved(account, amount, total);
        return total;
    }

    function setLimit(uint128 value) external onlyOwner {
        limit = value;
        emit LimitChanged(value);
    }

    function setActive(bool value) external onlyOwner {
        active = value;
        emit ActiveChanged(value);
    }

    function balanceOf(address account) external view returns (uint256) {
        return purchases[account];
    }

    receive() external payable {}
}
