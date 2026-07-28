// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

abstract contract EpochState {
    uint64 internal inheritedEpoch;
}

abstract contract GuardianState {
    address internal guardian;
}

contract YieldVault is EpochState, GuardianState {
    address public owner;
    uint256 public total;
    mapping(address => uint256) public positions;
    uint128 public limit;
    bool public active;
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

    function addYield(uint256 amount) external returns (uint256) {
        require(active, "inactive");
        require(amount <= uint256(limit), "over limit");
        uint256 next = total + amount;
        total = next;
        positions[msg.sender] += amount;
        emit ValueAdded(msg.sender, amount, total);
        return total + 1;
    }

    function withdraw(address account, uint256 amount) external onlyOwner returns (uint256) {
        require(positions[account] >= amount, "insufficient");
        positions[account] -= amount;
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
        return positions[account];
    }

    receive() external payable {}
}
